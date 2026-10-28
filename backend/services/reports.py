"""
Canadian capital gains report (adjusted cost base, ACB). Pure functions over the stored trades: no prices, no
exchange rates, no database, so the maths can be tested on its own (tests/test_capital_gains.py).

Rules (individual investor):
  - only trades in taxable accounts count: NON_REGISTERED, or no account set (None). TFSA / RRSP / FHSA / RESP
    trades are left out of the gains, but a purchase in them still counts for the superficial loss check.
  - ACB is pooled per security across every taxable trade, replayed oldest first (same order as LEDGER_ORDER) over
    all years, so a sale's ACB carries over from earlier years: a buy adds quantity and cost, a sale takes
    average cost x quantity sold out of the pool.
  - dates are Toronto calendar dates (a 9 pm Dec 31 trade is stored as Jan 1 UTC but is a Dec 31 trade). A sale
    counts in the tax year of its settlement date: stocks settle T+1 business days (T+2 for trades before
    2024-05-28), crypto on the trade date.
  - commissions aren't stored, so outlays and expenses are always 0.
  - superficial loss: only flagged, never adjusted (the denied amount depends on things Zenith can't see), but the
    flag says how much of the loss may be denied (CRA's least of sold / bought in the window / held at its end).
  - interlisted shares (SHOP and SHOP.TO) are one identical property for CRA but separate pools here: warned about.
"""
import csv
import io
import re
import heapq
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from backend.services.asset_services import as_quantity, sell_tolerance, toronto_date

TAXABLE_ACCOUNTS = (None, "NON_REGISTERED")
SUPERFICIAL_DAYS = 30
INCLUSION_RATE = Decimal("0.5")
CENT = Decimal("0.01")
T1_SETTLEMENT_FROM = date(2024, 5, 28)  # Canada and the US moved from T+2 to T+1 settlement for trades from this day
CRA_SUPERFICIAL_LOSS_URL = (
    "https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/tax-return/"
    "completing-a-tax-return/personal-income/line-12700-capital-gains/capital-losses-deductions.html#SL")

REPORT_NOTES = [
    "Only trades in non-registered accounts, or with no account set, are counted. TFSA, RRSP, FHSA and RESP trades "
    "are left out.",
    "ACB is the average cost of all your taxable buys of the same security, carried over from earlier years.",
    "Commissions and fees aren't stored in Zenith, so outlays and expenses are 0. Add them yourself: they lower "
    "the gain.",
    "Dates are Toronto calendar dates. A sale counts in the tax year it settles: stocks settle 1 business day after "
    "the trade date (2 business days for trades before May 28, 2024), so a stock sold on the last trading day of "
    "December counts in the next year. Crypto counts on its trade date. Only weekends and the Christmas and New "
    "Year holidays are skipped, so check your broker's settlement date for a sale at the very end of December.",
    "Amounts entered in USD or EUR are converted to CAD when the trade is saved. A trade saved more than a day "
    "after it happened uses Yahoo Finance's daily closing rate (USD/CAD or EUR/CAD) for its trade date in Toronto "
    "time, or the previous trading day's close on weekends and holidays. A trade logged the day it happened uses "
    "open.er-api's rate at the time it was saved. If the trade-date rate wasn't available, or the trade was saved "
    "before Zenith used trade-date rates, the rate of the day it was entered was used. CRA expects the Bank of "
    "Canada rate for the day (or its annual average), which can differ slightly.",
    "Superficial losses are only flagged, never adjusted: the 30-day window is counted on trade dates, and Zenith "
    "can't see accounts of your spouse or other affiliated persons.",
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


# ---------------------------------------------------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------------------------------------------------
def trade_date(t) -> date:
    """The trade's calendar date in Toronto."""
    return toronto_date(t.created_at)


@lru_cache(maxsize=256)
def _year_end_holidays(year: int) -> frozenset:
    """
    The market holidays that can move a settlement across the year end (Canadian rules): New Year's Day, Christmas
    and Boxing Day, each moved to the next free weekday when it falls on a weekend (Dec 25 on a Saturday -> Monday
    27, Boxing Day -> Tuesday 28). Other holidays only shift a settlement within the same year, so they're left out.
    """
    days: set[date] = set()
    for day in (date(year, 1, 1), date(year, 12, 25), date(year, 12, 26)):
        while day.weekday() >= 5 or day in days:
            day += timedelta(days=1)
        days.add(day)
    return frozenset(days)


def _business_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _year_end_holidays(day.year)


def settlement_date(t) -> date:
    """
    When the sale (or buy) settles, which decides its tax year. Stocks: T+1 business days for trades from
    2024-05-28, T+2 before. Crypto has no settlement cycle: the trade date.
    """
    day = trade_date(t)
    if str(t.asset_type) == "crypto":
        return day
    remaining = 1 if day >= T1_SETTLEMENT_FROM else 2
    while remaining:
        day += timedelta(days=1)
        if _business_day(day):
            remaining -= 1
    return day


def tax_year(t) -> int:
    return settlement_date(t).year


# ---------------------------------------------------------------------------------------------------------------------
# Securities
# ---------------------------------------------------------------------------------------------------------------------
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


def interlisted_pairs(trades) -> dict[str, tuple[str, str]]:
    """
    {ticker: (US ticker, Toronto ticker)} for every stock traded in a taxable account under both its Toronto (.TO)
    and a US listing (no suffix), e.g. SHOP and SHOP.TO. CRA treats the two as one identical property (one ACB pool
    and one superficial loss check); Zenith keeps them apart, so the report warns instead. The ticker alone can't
    tell whether it's really the same company (T is AT&T, T.TO is Telus), which the warning says.
    """
    tickers = {str(t.api_id).upper() for t in trades if is_taxable(t) and str(t.asset_type) != "crypto"}
    pairs = {}
    for ticker in tickers:
        if ticker.endswith(".TO") and ticker[:-3] in tickers and "." not in ticker[:-3]:
            us = ticker[:-3]
            pairs[us] = pairs[ticker] = (us, ticker)
    return pairs


def _interlisted_warning(us: str, toronto: str) -> str:
    return (f"{us} and {toronto}: if these are the same company's shares listed in the US and in Toronto, CRA "
            f"treats them as identical property, so they share one ACB pool and count for each other's superficial "
            f"loss check. Zenith keeps them apart, so work out the combined ACB yourself (in CAD) before you file. "
            f"Some tickers belong to different companies (T is AT&T, T.TO is Telus); then nothing changes.")


# ---------------------------------------------------------------------------------------------------------------------
# Superficial loss
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class _Pool:
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)  # total ACB in CAD of what is held
    currencies: set = field(default_factory=set)  # non-CAD currencies of the buys still in the pool
    # possible superficial losses whose taxable repurchase may still be bought: a heap of (from when, sale date,
    # amount). Once a sale comes after "from when" the loss moves into the totals below, which every later sale of
    # the pool shares. Kept as running totals, not a list each sale rescans: a long buy/sell history (an import of
    # thousands of rows) would otherwise make the report quadratic in time and in size.
    pending_losses: list = field(default_factory=list)
    linked_count: int = 0
    linked_total: Decimal = Decimal(0)
    linked_first: date | None = None
    linked_last: date | None = None

    def link_due_losses(self, sale_key) -> None:
        while self.pending_losses and self.pending_losses[0][0] < sale_key:
            _, day, amount = heapq.heappop(self.pending_losses)
            self.linked_count += 1
            self.linked_total += amount
            self.linked_first = day if self.linked_first is None else min(self.linked_first, day)
            self.linked_last = day if self.linked_last is None else max(self.linked_last, day)


class _Holdings:
    """Every account's trades of one security by Toronto trade date: "bought in the window?", "held at its end?"."""

    def __init__(self):
        self.days: list[date] = []  # trade date of each trade, in ledger order (so never decreasing)
        self.running: list[Decimal] = []  # quantity held (all accounts) after each trade
        self.buys: list[tuple[date, tuple, Decimal, bool]] = []  # (day, ledger key, quantity, taxable)
        self.buy_days: list[date] = []  # the day of each buy (never decreasing), to find a window by bisection
        # running totals over the buys, so a window's sums cost two lookups instead of a pass over every buy in it
        self.bought_before: list[Decimal] = [Decimal(0)]  # [i] = quantity of the first i buys
        self.taxable_before: list[int] = [0]  # [i] = how many of the first i buys are taxable
        self.taxable_index: list[int] = []  # positions in `buys` of the taxable buys, in order

    def add(self, t):
        qty = as_quantity(t.quantity)
        held = self.running[-1] if self.running else Decimal(0)
        held = held + qty if str(t.action) == "BUY" else max(Decimal(0), held - qty)
        day = trade_date(t)
        self.days.append(day)
        self.running.append(held)
        if str(t.action) == "BUY":
            taxable = is_taxable(t)
            if taxable:
                self.taxable_index.append(len(self.buys))
            self.buys.append((day, ledger_key(t), qty, taxable))
            self.buy_days.append(day)
            self.bought_before.append(self.bought_before[-1] + qty)
            self.taxable_before.append(self.taxable_before[-1] + taxable)

    def window(self, first: date, last: date) -> tuple[Decimal, int, int, tuple | None]:
        """Buys from `first` to `last`: (quantity bought, how many, how many taxable, key of the first taxable)."""
        lo, hi = bisect_left(self.buy_days, first), bisect_right(self.buy_days, last)
        taxable = self.taxable_before[hi] - self.taxable_before[lo]
        # buys are in ledger order, so the first taxable one at or after `lo` has the smallest key of the window
        first_taxable = self.buys[self.taxable_index[bisect_left(self.taxable_index, lo)]][1] if taxable else None
        return self.bought_before[hi] - self.bought_before[lo], hi - lo, taxable, first_taxable

    def held_at_end_of(self, day: date) -> Decimal:
        i = bisect_right(self.days, day)
        return self.running[i - 1] if i else Decimal(0)


@dataclass
class _Superficial:
    flagged: bool = False
    denied: Decimal = Decimal(0)  # estimated part of the loss CRA may deny, positive CAD
    notes: list = field(default_factory=list)
    taxable_repurchase_from: tuple | None = None  # ledger key from when a taxable repurchase is in the ACB pool


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _superficial(sale, loss: Decimal, holdings: _Holdings, today: date) -> _Superficial:
    """
    CRA's test: the same security was bought (in any account) from 30 days before to 30 days after the sale, and
    some is still owned at the end of the 30th day after. The part that may be denied is the loss x the least of
    (units sold, units bought in that window, units held at its end) / units sold, so an old holding outside the
    window alone never makes a loss superficial. Calendar days in Toronto, counted on trade dates.
    """
    result = _Superficial()
    sale_day = trade_date(sale)
    last_day = sale_day + timedelta(days=SUPERFICIAL_DAYS)
    still_open = last_day >= today

    sold = as_quantity(sale.quantity)
    bought, buy_count, taxable_count, first_taxable = holdings.window(sale_day - timedelta(days=SUPERFICIAL_DAYS),
                                                                       last_day)
    held_at_end = holdings.held_at_end_of(last_day)
    denied_units = min(sold, bought, held_at_end)

    if denied_units <= sell_tolerance(sold):
        if still_open:
            result.notes.append(f"If you buy it again by {last_day.isoformat()} (in any account) and still own it "
                                f"then, this loss could become a superficial loss.")
        return result

    result.flagged = True
    result.denied = _cents(loss * denied_units / sold) if denied_units < sold else _cents(loss)
    portion = ("all of this loss" if denied_units >= sold - sell_tolerance(sold) else
               f"part of it: {_qty(denied_units)} of the {_qty(sold)} units sold")
    result.notes.append(
        f"Possible superficial loss: you bought {_qty(bought)} of this security within 30 days before or after this "
        f"sale (in any account, TFSA and RRSP included) and held {_qty(held_at_end)} at the end of the 30 days "
        f"after it. CRA may deny all or part of this loss; by its formula that's {portion} (about "
        f"CA${result.denied:,.2f}).")

    if taxable_count:
        result.notes.append("A denied loss isn't lost: it's added to the ACB of the shares bought back in your "
                            "non-registered account, which lowers the gain (or raises the loss) when you sell them.")
        # from this sale on if a taxable repurchase came before it, otherwise from the first one after it
        sale_key = ledger_key(sale)
        result.taxable_repurchase_from = sale_key if first_taxable <= sale_key else first_taxable
    if buy_count > taxable_count:
        result.notes.append("When the shares bought back are in a TFSA, RRSP or other registered account, the "
                            "denied part is lost for good: it isn't added to any ACB.")
    if still_open:
        result.notes.append(f"The 30 days after this sale end on {last_day.isoformat()}; selling everything by "
                            f"then would change this.")
    return result


def _money(value: Decimal) -> Decimal:
    # exact cents in the report and its CSV; the API's response model turns them into JSON numbers. As floats here
    # the CSV lost cents on amounts past ~CA$10^14 (a float holds ~16 digits).
    return _cents(value)


def capital_gains(trades, year: int, now: datetime | None = None) -> dict:
    """
    The report for one tax year (sales settling in that calendar year): every taxable sale with its proceeds, ACB
    and gain, the year's totals, warnings and notes. `trades` are all of one user's trades, in any order and any
    account.
    """
    today = toronto_date(now or datetime.now(timezone.utc))
    trades = sorted(trades, key=ledger_key)
    keys = security_keys(trades)
    interlisted = interlisted_pairs([t for t in trades if tax_year(t) <= year])

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

        # possible superficial losses earlier on whose taxable repurchase is part of what this sale takes out
        sale_key = ledger_key(t)
        pool.link_due_losses(sale_key)
        linked = (pool.linked_count, pool.linked_total, pool.linked_first, pool.linked_last)

        if oversold or qty >= pool.quantity - sell_tolerance(pool.quantity):
            # a fresh pool, but losses whose buy-back is still to come stay with it: the shares bought back go into
            # this new pool, so its later sales may get the denied loss added to their ACB
            pools[key] = pool = _Pool(pending_losses=pool.pending_losses)
        else:
            pool.quantity -= qty
            pool.cost -= acb

        proceeds = _cents(price * qty)
        acb = _cents(acb)
        gain = proceeds - acb

        settles = settlement_date(t)
        superficial = _Superficial()
        # a sale settling after the year can't change this year's report: the losses it could link only reach later
        # sales of the same security, which settle later still
        if gain < 0 and settles.year <= year:
            superficial = _superficial(t, -gain, holdings[key], today)
            if superficial.taxable_repurchase_from is not None:
                # the repurchase may still be bought later; sales from then on carry a note (see below)
                heapq.heappush(pool.pending_losses,
                               (superficial.taxable_repurchase_from, trade_date(t), superficial.denied))

        if settles.year != year:
            continue

        notes.extend(superficial.notes)
        linked_count, linked_total, first_day, last_day = linked
        if linked_count == 1:
            notes.append(f"Its ACB may be too low: the possible superficial loss on {first_day.isoformat()} (up to "
                         f"CA${linked_total:,.2f}) would be added to the ACB of the shares bought back, which raises "
                         f"the ACB of this sale if CRA denies it.")
        elif linked_count > 1:
            notes.append(f"Its ACB may be too low: {linked_count} possible superficial losses from "
                         f"{first_day.isoformat()} to {last_day.isoformat()} (up to CA${linked_total:,.2f} in all) "
                         f"would be added to the ACB of the shares bought back, which raises the ACB of this sale if "
                         f"CRA denies them.")
        foreign = _foreign(t)
        if foreign:
            notes.append(f"Entered in {foreign}: converted to CAD with Yahoo Finance's daily {foreign}/CAD close for "
                         f"the trade date (Toronto time; the previous trading day's on weekends and holidays), or "
                         f"open.er-api's rate when it was saved the day it happened (also used when the trade-date "
                         f"rate wasn't available). Check it against the Bank of Canada rate for that day.")
        if acb_currencies:
            notes.append(f"Its ACB includes buys entered in {', '.join(acb_currencies)}, converted the same way.")
        pair = interlisted.get(str(t.api_id).upper()) if str(t.asset_type) != "crypto" else None
        if pair:
            notes.append(f"Also traded as {pair[1] if str(t.api_id).upper() == pair[0] else pair[0]}: if it's the "
                         f"same company, CRA pools both listings into one ACB (see the warning above).")

        sales.append({
            "id": str(t.id),
            "date": trade_date(t).isoformat(),
            "settlement_date": settles.isoformat(),
            "symbol": str(t.symbol),
            "asset_type": str(t.asset_type),
            "quantity": float(qty),
            "proceeds": _money(proceeds),
            "acb": _money(acb),
            "outlays": 0.0,
            "gain": _money(gain),
            "currency_entered": getattr(t, "currency_entered", None),
            "foreign_currency": bool(foreign or acb_currencies),
            "superficial_loss": superficial.flagged,
            "superficial_amount": _money(superficial.denied),
            "acb_may_rise": linked_count > 0,
            "interlisted": bool(pair),
            "oversold": oversold,
            "notes": notes,
        })

    warnings = [_interlisted_warning(*pair) for pair in sorted(set(interlisted.values()))]
    return {
        "year": year,
        "currency": "CAD",
        "sales": sales,
        "totals": totals(sales),
        "warnings": warnings,
        "notes": list(REPORT_NOTES),
        "superficial_loss_url": CRA_SUPERFICIAL_LOSS_URL,
    }


def totals(sales) -> dict:
    """Sums of the rows as shown (cents), so the totals always add up with the table and the CSV."""
    proceeds = sum((Decimal(str(s["proceeds"])) for s in sales), Decimal(0))
    acb = sum((Decimal(str(s["acb"])) for s in sales), Decimal(0))
    gains = sum((Decimal(str(s["gain"])) for s in sales if s["gain"] > 0), Decimal(0))
    losses = sum((Decimal(str(s["gain"])) for s in sales if s["gain"] < 0), Decimal(0))
    # the part of `losses` that may be superficial (flagged, not taken out): positive CAD
    superficial = sum((Decimal(str(s.get("superficial_amount", 0))) for s in sales if s.get("superficial_loss")),
                      Decimal(0))
    net = gains + losses
    # a net capital loss isn't taxed (it can be carried back 3 years or forward), so nothing is taxable then
    taxable = _cents(net * INCLUSION_RATE) if net > 0 else Decimal(0)
    return {"proceeds": _money(proceeds), "acb": _money(acb), "net": _money(net), "gains": _money(gains),
            "losses": _money(losses), "possibly_superficial": _money(superficial),
            "taxable_at_50pct": _money(taxable)}


def taxable_sale_years(trades) -> list[int]:
    """Tax years (by settlement date) with at least one taxable sale, newest first."""
    return sorted({tax_year(t) for t in trades if str(t.action) == "SELL" and is_taxable(t)}, reverse=True)


# A spreadsheet runs a cell that starts with one of these as a formula ("=HYPERLINK(...)" in a symbol)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_START) and not _PLAIN_NUMBER.match(text):
        return "'" + text
    return text


def _amount(value) -> str:
    return f"{(value if isinstance(value, Decimal) else Decimal(str(value))).quantize(CENT):f}"


CSV_HEADER = ["Trade date", "Settlement date", "Symbol", "Type", "Quantity", "Proceeds (CAD)", "ACB (CAD)",
              "Outlays (CAD)", "Gain or loss (CAD)", "Currency entered", "Superficial loss?",
              "Possibly denied (CAD)", "Oversold?", "Notes"]


def report_csv(report: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for s in report["sales"]:
        writer.writerow([safe_cell(cell) for cell in [
            s["date"], s["settlement_date"], s["symbol"], s["asset_type"],
            f"{Decimal(str(s['quantity'])).normalize():f}",
            _amount(s["proceeds"]), _amount(s["acb"]), _amount(s["outlays"]), _amount(s["gain"]),
            s["currency_entered"] or "CAD", "Yes" if s["superficial_loss"] else "No",
            _amount(s["superficial_amount"]) if s["superficial_loss"] else "",
            "Yes" if s["oversold"] else "No", " ".join(s["notes"]),
        ]])
    t = report["totals"]
    summary = (f"Gains {_amount(t['gains'])}; losses {_amount(t['losses'])}"
               + (f" (includes up to {_amount(t['possibly_superficial'])} of possibly superficial losses)"
                  if t["possibly_superficial"] else "")
               + f"; 50% of a net gain taxable: {_amount(t['taxable_at_50pct'])}. "
               + " ".join(report.get("warnings", [])) + (" " if report.get("warnings") else "")
               + "Not tax advice.")
    writer.writerow([safe_cell(cell) for cell in [
        f"Total {report['year']}", "", "", "", "", _amount(t["proceeds"]), _amount(t["acb"]), "0.00",
        _amount(t["net"]), "", "", "", "", summary,
    ]])
    return out.getvalue()
