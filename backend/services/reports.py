"""
Canadian capital gains report (adjusted cost base, ACB). Pure functions over the stored trades: no prices, no
exchange rates, no database, so the maths can be tested on its own (tests/test_capital_gains.py).

Rules (individual investor):
  - only trades in taxable accounts count: NON_REGISTERED, or no account set (None). TFSA / RRSP / FHSA / RESP
    trades are left out of the gains, but a purchase in them still counts for the superficial loss check.
  - ACB is pooled per security across every taxable trade, replayed oldest first (same order as LEDGER_ORDER) over
    all years, so a sale's ACB carries over from earlier years: a buy adds quantity and cost, a sale takes
    average cost x quantity sold out of the pool.
  - commissions aren't stored, so outlays and expenses are always 0.
  - superficial loss: only flagged, never adjusted (the denied amount depends on things Zenith can't see).
"""
import csv
import io
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from backend.services.asset_services import as_quantity, sell_tolerance

TAXABLE_ACCOUNTS = (None, "NON_REGISTERED")
SUPERFICIAL_DAYS = 30
INCLUSION_RATE = Decimal("0.5")
CENT = Decimal("0.01")
CRA_SUPERFICIAL_LOSS_URL = (
    "https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/tax-return/"
    "completing-a-tax-return/personal-income/line-12700-capital-gains/capital-losses-deductions.html#SL")

REPORT_NOTES = [
    "Only trades in non-registered accounts, or with no account set, are counted. TFSA, RRSP, FHSA and RESP trades "
    "are left out.",
    "ACB is the average cost of all your taxable buys of the same security, carried over from earlier years.",
    "Commissions and fees aren't stored in Zenith, so outlays and expenses are 0. Add them yourself: they lower "
    "the gain.",
    "Dates are in UTC (the time each trade was logged), so a trade made late in the evening can fall on the next "
    "day, or year.",
    "Trades entered in USD or EUR were converted to CAD at the exchange rate of the day they were entered in "
    "Zenith, not necessarily the trade-date rate CRA expects. Backdated foreign trades may differ.",
    "Superficial losses are only flagged, never adjusted, and Zenith can't see accounts of your spouse or other "
    "affiliated persons.",
    "Not tax advice. Check these numbers against your broker's T5008 and other tax slips.",
]


def _naive_utc(value: datetime) -> datetime:
    # trades are stored as naive UTC; a value with an offset (e.g. from a test) is converted first
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def ledger_key(t):
    """Python twin of LEDGER_ORDER (time, then BUY before SELL, then id), so same-tick trades replay the same way."""
    return _naive_utc(t.created_at), str(t.action), str(t.id)


def is_taxable(t) -> bool:
    return getattr(t, "account_type", None) in TAXABLE_ACCOUNTS


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _foreign(t) -> str | None:
    """The currency the price was typed in when it wasn't CAD (older trades with no currency count as CAD)."""
    code = str(getattr(t, "currency_entered", None) or "").upper()
    return code if code and code != "CAD" else None


def security_keys(trades) -> dict:
    """
    {trade id: security key}. A security is (asset type, api_id, coin_id). Crypto trades without a coin_id (logged
    before it was stored) join the one coin that shares their ticker; when several coins share it they stay apart,
    since there is no way to tell which one they were.
    """
    coins = defaultdict(set)
    for t in trades:
        if t.asset_type == "crypto" and getattr(t, "coin_id", None):
            coins[str(t.api_id).upper()].add(t.coin_id)

    keys = {}
    for t in trades:
        api_id = str(t.api_id).upper()
        coin_id = getattr(t, "coin_id", None) if t.asset_type == "crypto" else None
        if t.asset_type == "crypto" and not coin_id and len(coins[api_id]) == 1:
            coin_id = next(iter(coins[api_id]))
        keys[str(t.id)] = (str(t.asset_type), api_id, coin_id)
    return keys


@dataclass
class _Pool:
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)  # total ACB in CAD of what is held
    currencies: set = field(default_factory=set)  # non-CAD currencies of the buys still in the pool


class _Holdings:
    """Every account's buys and sells of one security, to answer "bought within 30 days?" and "held at a time?"."""

    def __init__(self):
        self.buy_days: list[date] = []
        self.times: list[datetime] = []
        self.running: list[Decimal] = []  # quantity held (all accounts) after each trade

    def add(self, t):
        qty = as_quantity(t.quantity)
        held = self.running[-1] if self.running else Decimal(0)
        held = held + qty if str(t.action) == "BUY" else max(Decimal(0), held - qty)
        self.times.append(_naive_utc(t.created_at))
        self.running.append(held)
        if str(t.action) == "BUY":
            self.buy_days.append(_naive_utc(t.created_at).date())

    def bought_between(self, first: date, last: date) -> bool:
        return bisect_right(self.buy_days, last) > bisect_left(self.buy_days, first)

    def held_before(self, moment: datetime) -> Decimal:
        i = bisect_left(self.times, moment)
        return self.running[i - 1] if i else Decimal(0)


def _superficial(sale, holdings: _Holdings, now: datetime) -> tuple[bool, list[str]]:
    """
    CRA's test: the same security was bought (in any account) from 30 days before to 30 days after the sale, and
    some is still owned at the end of the 30th day after. Calendar days, in UTC.
    """
    sale_day = _naive_utc(sale.created_at).date()
    last_day = sale_day + timedelta(days=SUPERFICIAL_DAYS)
    period_end = datetime.combine(last_day + timedelta(days=1), datetime.min.time())  # midnight after the 30th day
    still_open = period_end > now

    if not holdings.bought_between(sale_day - timedelta(days=SUPERFICIAL_DAYS), last_day):
        if still_open:
            return False, [f"If you buy it again by {last_day.isoformat()} (in any account) and still own it then, "
                           f"this loss could become a superficial loss."]
        return False, []

    if holdings.held_before(min(period_end, now)) <= sell_tolerance(Decimal(0)):
        return False, []

    notes = ["Possible superficial loss: you bought this security within 30 days before or after this sale (in "
             "any account, TFSA and RRSP included) and still owned some 30 days after it. CRA may deny this loss "
             "and add it to the ACB of the shares bought back."]
    if still_open:
        notes.append(f"The 30 days after this sale end on {last_day.isoformat()}; selling everything by then "
                     f"would change this.")
    return True, notes


def _money(value: Decimal) -> float:
    return float(value)


def capital_gains(trades, year: int, now: datetime | None = None) -> dict:
    """
    The report for one calendar year (UTC): every taxable sale in that year with its proceeds, ACB and gain, the
    year's totals, and notes. `trades` are all of one user's trades, in any order and any account.
    """
    now = _naive_utc(now or datetime.now(timezone.utc))
    trades = sorted(trades, key=ledger_key)
    keys = security_keys(trades)

    holdings = defaultdict(_Holdings)
    for t in trades:
        holdings[keys[str(t.id)]].add(t)

    pools = defaultdict(_Pool)
    sales = []
    for t in trades:
        if not is_taxable(t):
            continue
        key = keys[str(t.id)]
        pool = pools[key]
        qty = as_quantity(t.quantity)
        price = Decimal(str(t.price_of_one))  # CAD

        if str(t.action) == "BUY":
            pool.quantity += qty
            pool.cost += price * qty
            if _foreign(t):
                pool.currencies.add(_foreign(t))
            continue

        # SELL
        notes = []
        oversold = qty > pool.quantity + sell_tolerance(pool.quantity)
        if oversold:
            # the units the taxable trades don't hold have no known cost: count the whole pool, keep the full
            # proceeds (what the broker reports) and say the gain is likely too high
            missing = qty - pool.quantity
            acb = pool.cost
            notes.append(f"This sale is {missing.normalize():f} more than your non-registered (or not set) trades "
                         f"held at the time, so the ACB of those units is unknown and the gain is likely overstated. "
                         f"Check the account types of earlier buys.")
        elif qty >= pool.quantity - sell_tolerance(pool.quantity):
            acb = pool.cost  # sells everything: take exactly what's left, no rounding crumbs
        else:
            acb = pool.cost * qty / pool.quantity
        acb_currencies = sorted(pool.currencies)

        if oversold or qty >= pool.quantity - sell_tolerance(pool.quantity):
            pools[key] = _Pool()
        else:
            pool.quantity -= qty
            pool.cost -= acb

        sale_date = _naive_utc(t.created_at)
        if sale_date.year != year:
            continue

        proceeds = _cents(price * qty)
        acb = _cents(acb)
        gain = proceeds - acb

        superficial = False
        if gain < 0:
            superficial, loss_notes = _superficial(t, holdings[key], now)
            notes.extend(loss_notes)

        foreign = _foreign(t)
        if foreign:
            notes.append(f"Entered in {foreign}: converted to CAD at the rate of the day it was entered in Zenith, "
                         f"which may differ from the trade-date rate CRA expects.")
        if acb_currencies:
            notes.append(f"Its ACB includes buys entered in {', '.join(acb_currencies)}, converted the same way.")

        sales.append({
            "id": str(t.id),
            "date": sale_date.date().isoformat(),
            "symbol": str(t.symbol),
            "asset_type": str(t.asset_type),
            "quantity": float(qty),
            "proceeds": _money(proceeds),
            "acb": _money(acb),
            "outlays": 0.0,
            "gain": _money(gain),
            "currency_entered": getattr(t, "currency_entered", None),
            "foreign_currency": bool(foreign or acb_currencies),
            "superficial_loss": superficial,
            "oversold": oversold,
            "notes": notes,
        })

    return {
        "year": year,
        "currency": "CAD",
        "sales": sales,
        "totals": totals(sales),
        "notes": list(REPORT_NOTES),
        "superficial_loss_url": CRA_SUPERFICIAL_LOSS_URL,
    }


def totals(sales) -> dict:
    """Sums of the rows as shown (cents), so the totals always add up with the table and the CSV."""
    proceeds = sum((Decimal(str(s["proceeds"])) for s in sales), Decimal(0))
    acb = sum((Decimal(str(s["acb"])) for s in sales), Decimal(0))
    gains = sum((Decimal(str(s["gain"])) for s in sales if s["gain"] > 0), Decimal(0))
    losses = sum((Decimal(str(s["gain"])) for s in sales if s["gain"] < 0), Decimal(0))
    net = gains + losses
    # a net capital loss isn't taxed (it can be carried back 3 years or forward), so nothing is taxable then
    taxable = _cents(net * INCLUSION_RATE) if net > 0 else Decimal(0)
    return {"proceeds": _money(proceeds), "acb": _money(acb), "net": _money(net), "gains": _money(gains),
            "losses": _money(losses), "taxable_at_50pct": _money(taxable)}


def taxable_sale_years(trades) -> list[int]:
    """Calendar years (UTC) with at least one taxable sale, newest first."""
    return sorted({_naive_utc(t.created_at).year for t in trades if str(t.action) == "SELL" and is_taxable(t)},
                  reverse=True)


# A spreadsheet runs a cell that starts with one of these as a formula ("=HYPERLINK(...)" in a symbol)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_START) and not _PLAIN_NUMBER.match(text):
        return "'" + text
    return text


def _amount(value: float) -> str:
    return f"{Decimal(str(value)).quantize(CENT):f}"


CSV_HEADER = ["Date (UTC)", "Symbol", "Type", "Quantity", "Proceeds (CAD)", "ACB (CAD)", "Outlays (CAD)",
              "Gain or loss (CAD)", "Currency entered", "Superficial loss?", "Oversold?", "Notes"]


def report_csv(report: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for s in report["sales"]:
        writer.writerow([safe_cell(cell) for cell in [
            s["date"], s["symbol"], s["asset_type"], f"{Decimal(str(s['quantity'])).normalize():f}",
            _amount(s["proceeds"]), _amount(s["acb"]), _amount(s["outlays"]), _amount(s["gain"]),
            s["currency_entered"] or "CAD", "Yes" if s["superficial_loss"] else "No",
            "Yes" if s["oversold"] else "No", " ".join(s["notes"]),
        ]])
    t = report["totals"]
    writer.writerow([safe_cell(cell) for cell in [
        f"Total {report['year']}", "", "", "", _amount(t["proceeds"]), _amount(t["acb"]), "0.00", _amount(t["net"]),
        "", "", "", f"Gains {_amount(t['gains'])}; losses {_amount(t['losses'])}; 50% of a net gain taxable: "
                    f"{_amount(t['taxable_at_50pct'])}. Not tax advice.",
    ]])
    return out.getvalue()
