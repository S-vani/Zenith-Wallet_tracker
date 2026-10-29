"""
CSV import and export of trades (routes in backend/routes/imports.py).

Export writes Zenith's own template; import reads that template plus Wealthsimple's activities export and
Questrade's account activity export, and turns every row into the same shape a manual trade has. Nothing here
touches the database: the routes do that, so all of this is plain, testable parsing (resolve_tsx_listings is the
one step that asks the price source, for broker rows that don't say which exchange they're on).

The broker layouts come from their exports as seen in other open-source importers (not from official docs), so
column matching is deliberately loose: case, spaces and punctuation in headers don't matter and a few aliases are
accepted for each column.
"""
import asyncio
import csv
import io
import logging
import math
import re
import time as clock
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from backend.schemas.assets import ACCOUNT_TYPES, FUTURE_SKEW, MAX_PRICE, MAX_QUANTITY, MIN_AMOUNT, OLDEST_DATE
from backend.services import asset_services
from backend.services.asset_services import as_quantity, get_conversion_factor, sell_tolerance

log = logging.getLogger(__name__)

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
SUPPORTED_CURRENCIES = ("CAD", "USD", "EUR")  # what get_conversion_factor knows

FORMAT_LABELS = {"zenith": "Zenith template", "wealthsimple": "Wealthsimple", "questrade": "Questrade"}

EXPORT_COLUMNS = ["date", "action", "asset_type", "symbol", "quantity", "price", "currency", "account_type", "coin_id"]

# Broker exports usually only give a day. 21:00 UTC is the end of the trading day (4 pm in Toronto in winter, 5 pm in
# summer), so a file's trade replays after anything logged by hand earlier that day (a hand-logged buy and a file
# sell of the same day stay in that order), and it's still the same calendar day from Vancouver to Western Europe.
# The preview shows only the day. Anything after 21:00 is handled by place_date_only_sells.
DATE_ONLY_HOUR = 21

# Whatever a manual trade accepts (any text up to 32 characters, see CreateTransaction.symbol), so an export always
# reads back in ("usd+", "BRK-B", "XEQT.TO"), except control characters and a first character that makes a
# spreadsheet run the cell as a formula (= + - @), which keeps formula text out of the database.
SYMBOL_PATTERN = re.compile(r"[^\s=+\-@\x00-\x1f\x7f][^\x00-\x1f\x7f]{0,31}")
COIN_ID_PATTERN = re.compile(r"[a-z0-9-]{1,80}")

# Well-known coins. A Zenith row with no asset_type and one of these symbols is ambiguous ("BTC" and "ETH" are also
# US ETFs, "SOL" and "LTC" are stocks), so it has to say which. Wealthsimple rows use it to spot crypto trades outside
# an account named "Crypto" (a CAD row with no exchange and no FX conversion).
KNOWN_CRYPTO = frozenset({
    "BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "SOL", "ADA", "DOGE", "TRX", "DOT", "MATIC", "POL", "LTC", "SHIB",
    "AVAX", "LINK", "XLM", "BCH", "ATOM", "UNI", "XMR", "ETC", "FIL", "HBAR", "APT", "ARB", "NEAR", "ICP", "ALGO",
    "AAVE", "PEPE", "SUI", "TON", "DAI", "WBTC", "MANA", "SAND", "AXS", "XTZ", "EOS", "GRT", "CRV", "MKR", "LDO",
    "RNDR", "RENDER", "INJ", "SEI", "TIA", "BONK", "WIF", "FLOKI", "ENA", "JUP", "PYTH", "STX", "IMX", "OP", "QNT",
})


class RowError(ValueError):
    """A row that can't be imported; the message is shown next to it."""


class FileError(ValueError):
    """The whole file can't be read (unknown layout, missing columns, too many rows)."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------------------------------------------------
# Cells, numbers and dates
# ---------------------------------------------------------------------------------------------------------------------
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
NEGATIVE_NUMBER = re.compile(r"-\d+(\.\d+)?([eE][-+]?\d+)?")


def csv_safe(value) -> str:
    """
    A cell that spreadsheet apps won't run as a formula: text starting with = + - @ (or a tab / carriage return)
    gets a leading apostrophe, which Excel and Sheets show as plain text. Plain negative numbers stay numbers.
    """
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_START) and not NEGATIVE_NUMBER.fullmatch(text):
        return "'" + text
    return text


def clean_cell(value) -> str:
    """Trimmed text, with csv_safe's apostrophe taken off again so an export reads back as it was written."""
    text = "" if value is None else str(value).strip()
    if len(text) > 1 and text[0] == "'" and text[1] in "=+-@":
        text = text[1:]
    return text


def _short(text, limit: int = 24) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…"


# A thousands group starts with 1-9: "0,500" is a decimal (0.5), never five hundred
THOUSANDS = re.compile(r"[-+]?[1-9]\d{0,2}(,\d{3})+(\.\d*)?")
DOT_THOUSANDS = re.compile(r"[-+]?[1-9]\d{0,2}(\.\d{3})+")
PLAIN_NUMBER = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")
# spaces spreadsheets put between thousands: normal, no-break (U+00A0), narrow no-break (U+202F, French Excel),
# thin (U+2009) and figure (U+2007)
NUMBER_SPACES = str.maketrans("", "", "     ")
# Bigger than any quantity, price or net amount can be (1e9 shares at 1e9 each is 1e18); also keeps exponents like
# "1e999999" from overflowing later maths
MAX_MAGNITUDE = 20


def parse_number(value, label: str, decimal_comma: bool = False) -> Decimal | None:
    """
    A number from a cell, or None when it's empty. Accepts "1234.5", "1,234.50", "1 234,50", "$12.30", "(5.00)"
    (accounting negative) and, in semicolon-separated files (European spreadsheets), "1,5" and "1.234.567,89".
    Raises RowError otherwise.

    In a semicolon file a single dot followed by exactly three digits ("1.234", "12.500") is refused as ambiguous:
    it's a thousands separator in a German or French spreadsheet but a decimal point when the number was pasted from
    elsewhere, and guessing wrong is off by 1000x. "0.123", "1.5" and "1.234.567" can only be read one way.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise RowError(f"{label} isn't a number")
    if isinstance(value, Decimal):
        # already read from its cell (the broker formats work prices out first): re-reading its text in a
        # semicolon file took "1.913" for an ambiguous thousands separator
        if not value.is_finite():
            raise RowError(f"{label} isn't a number")
        if value and value.adjusted() > MAX_MAGNITUDE:
            raise RowError(f"{label} is too large")
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise RowError(f"{label} isn't a number")
        return Decimal(repr(float(value)))

    text = clean_cell(value).translate(NUMBER_SPACES)
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = re.sub(r"(?i)(ca|us|c|u)?\$", "", text)  # "$12", "US$12", "-$12"

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):  # 1.234,50
            text = text.replace(".", "").replace(",", ".")
        else:  # 1,234.50
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "") if not decimal_comma and THOUSANDS.fullmatch(text) else text.replace(",", ".")
    elif decimal_comma and DOT_THOUSANDS.fullmatch(text):
        if text.count(".") == 1:
            raise RowError(f"{label} \"{_short(value)}\" could mean {text} or {text.replace('.', '')}: write it "
                           "without a thousands separator (and with a decimal comma if it has decimals)")
        text = text.replace(".", "")  # 1.234.567

    if not PLAIN_NUMBER.fullmatch(text):
        raise RowError(f"{label} \"{_short(value)}\" isn't a number")
    try:
        number = Decimal(text)
        if not number.is_finite():
            raise RowError(f"{label} isn't a number")
        if number and number.adjusted() > MAX_MAGNITUDE:
            raise RowError(f"{label} is too large")
        return -number if negative else number
    except RowError:
        raise
    except (ArithmeticError, ValueError):  # decimal.InvalidOperation / Overflow are ArithmeticErrors
        raise RowError(f"{label} \"{_short(value)}\" isn't a number")


ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# "20240105", ISO's basic form: a day like any other (Python would read it as midnight UTC, the evening before in
# Toronto, so the trade landed on the previous day, and on Jan 1 in the previous tax year)
COMPACT_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})")
# Questrade: "2026-02-17 12:00:00 AM"
AM_PM = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*([AaPp][Mm])")
# A day and a time with no time zone: Zenith's own rows are UTC; Excel re-saves Questrade's "12:00:00 AM" as
# "2024-01-09 00:00:00" or "2024-01-09 0:00"
NAIVE_TIME = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?")
YMD_SLASH = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})(?:[ T].*)?")
DMY_OR_MDY = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:[ T].*)?")


def _real_day(year: int, month: int, day: int) -> bool:
    """Whether year / month / day is a date that exists."""
    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False


def _date_only(year: int, month: int, day: int) -> datetime:
    """A day with no time, stored at DATE_ONLY_HOUR UTC; a RowError when it isn't a real date."""
    try:
        return datetime(year, month, day, DATE_ONLY_HOUR)
    except ValueError:
        raise RowError("Date isn't a real calendar date")


def slash_date_order(cells) -> bool | None:
    """
    Whether a file's "1/9/2024"-style dates are day first (True), month first (False) or can't be told (None), from
    the dates that can only be read one way ("25/1/2024" is day first, "1/25/2024" month first): a spreadsheet
    re-saves every date of a file in the same style, so those settle the ambiguous ones.
    """
    day_first = month_first = 0
    for cell in cells:
        m = DMY_OR_MDY.fullmatch(clean_cell(cell))
        if m:
            first, second = int(m.group(1)), int(m.group(2))
            day_first += first > 12 >= second
            month_first += second > 12 >= first
    if day_first == month_first:
        return None
    return day_first > month_first


def parse_trade_date(value, now: datetime | None = None, day_first: bool | None = None) -> tuple[datetime, bool]:
    """
    (naive UTC datetime, whether the cell only had a day). Dates with an offset are converted to UTC, ones without
    are read as UTC (Zenith's export writes UTC). A day alone, or a day at exactly midnight with no time zone (what
    a spreadsheet makes of a day), is stored at DATE_ONLY_HOUR UTC. Like a manual trade it can't be in the future or
    before 1970. "1/9/2024" needs `day_first` (see slash_date_order) unless only one reading is a real date.
    Raises RowError, never anything else.
    """
    text = clean_cell(value)
    if not text:
        raise RowError("Missing date")
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        moment, date_only = _read_date(text, day_first)
        if (moment.date() > now.date()) if date_only else (moment > now + FUTURE_SKEW):
            raise RowError("Date is in the future")
        if moment < OLDEST_DATE:
            raise RowError("Date must be after 1970")
    except RowError:
        raise
    except (ValueError, ArithmeticError):  # "2024-02-30 10:00 AM", "10:99", an offset that overflows year 1
        raise RowError(f"Date \"{_short(text)}\" isn't a real date and time")
    return min(moment, now), date_only


def _read_date(text: str, day_first: bool | None) -> tuple[datetime, bool]:
    """(time, date only?) from a date cell's text in any of the formats brokers and spreadsheets write."""
    m = AM_PM.fullmatch(text)
    if m:
        day, hour, minute, second, half = m.groups()
        if int(hour) > 12:
            raise RowError(f"Date \"{_short(text)}\" has an hour past 12 with AM/PM")
        hour, minute, second = int(hour) % 12 + (12 if half.lower() == "pm" else 0), int(minute), int(second or 0)
        if hour == minute == second == 0:  # Questrade writes every trade at "12:00:00 AM": only the day is known
            return _date_only(*map(int, day.split("-"))), True
        return datetime.fromisoformat(day).replace(hour=hour, minute=minute, second=second), False
    if ISO_DATE.fullmatch(text):
        return _date_only(*map(int, text.split("-"))), True
    if (m := COMPACT_DATE.fullmatch(text)):
        return _date_only(*map(int, m.groups())), True
    m = NAIVE_TIME.fullmatch(text)
    if m:
        day, hour, minute, second = m.groups()
        hour, minute, second = int(hour), int(minute), int(second or 0)
        if hour == minute == second == 0:  # midnight with no time zone: a spreadsheet's way of writing a day
            return _date_only(*map(int, day.split("-"))), True
        return datetime.fromisoformat(day).replace(hour=hour, minute=minute, second=second), False
    if (m := YMD_SLASH.fullmatch(text)):
        return _date_only(*map(int, m.groups())), True
    if (m := DMY_OR_MDY.fullmatch(text)):
        # a spreadsheet re-saved the date in its own style: read it the one way it can be, or the file's way
        first, second, year = map(int, m.groups())
        as_dmy, as_mdy = _real_day(year, second, first), _real_day(year, first, second)
        if as_dmy and as_mdy and first != second:
            if day_first is None:
                raise RowError(f"Date \"{_short(text)}\" could be read two ways: use YYYY-MM-DD")
            day, month = (first, second) if day_first else (second, first)
        elif as_dmy:
            day, month = first, second
        elif as_mdy:
            day, month = second, first
        else:  # "25/14/2024": neither reading is a day, so it isn't ambiguous, just wrong
            raise RowError(f"Date \"{_short(text)}\" isn't a real calendar date")
        return _date_only(year, month, day), True
    try:
        moment = datetime.fromisoformat(text.removesuffix(" UTC"))
    except ValueError:
        raise RowError(f"Date \"{_short(text)}\" isn't a date we can read: use YYYY-MM-DD")
    if moment.tzinfo:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment, False


# ---------------------------------------------------------------------------------------------------------------------
# Account types and symbols
# ---------------------------------------------------------------------------------------------------------------------
UNKNOWN_ACCOUNT = "?"
# registered accounts Zenith has no type for; better left unset than called non-registered (taxes differ)
OTHER_REGISTERED = {"lira", "lif", "rrif", "rdsp", "lrsp", "rlsp", "prif", "rlif", "dpsp"}
NON_REGISTERED_WORDS = {"nonregistered", "personal", "joint", "individual", "margin", "cash", "taxable", "crypto",
                        "nonreg"}


def map_account_type(text) -> str | None:
    """
    One of ACCOUNT_TYPES from a broker's own words ("TFSA", "Individual TFSA", "Spousal RRSP", "Personal",
    "Individual margin", "Crypto", "Non-registered"...), None for an empty cell, UNKNOWN_ACCOUNT for anything else.
    """
    raw = clean_cell(text)
    if not raw:
        return None
    if raw.upper() in ACCOUNT_TYPES:
        return raw.upper()
    words = re.findall(r"[a-z]+", raw.lower())
    joined = "".join(words)
    if OTHER_REGISTERED & set(words):
        return UNKNOWN_ACCOUNT
    for account in ("TFSA", "FHSA", "RESP", "RRSP"):
        if account.lower() in words:
            return account
    if "rsp" in words:  # "Spousal RSP"
        return "RRSP"
    if joined.startswith("nonreg") or NON_REGISTERED_WORDS & set(words):
        return "NON_REGISTERED"
    return UNKNOWN_ACCOUNT


# Exchange names (as an "exchange" column might say them) -> Yahoo's ticker suffix
EXCHANGE_SUFFIX = {
    "tsx": ".TO", "xtse": ".TO", "tor": ".TO", "toronto": ".TO", "toronto_stock_exchange": ".TO",
    "tsxv": ".V", "tsx_v": ".V", "xtsx": ".V", "tsx_venture": ".V", "venture": ".V", "cdnx": ".V",
    "neo": ".NE", "xneo": ".NE", "cboe_canada": ".NE", "cboe_ca": ".NE", "aequitas": ".NE", "neoe": ".NE",
    "cse": ".CN", "cnsx": ".CN", "xcnq": ".CN", "canadian_securities_exchange": ".CN",
}
# Questrade's own suffixes -> Yahoo's (TSX Venture is ".VN" at Questrade, ".V" at Yahoo)
QUESTRADE_SUFFIX = {"TO": ".TO", "VN": ".V", "V": ".V", "CN": ".CN", "NE": ".NE"}
CANADIAN_SUFFIXES = (".TO", ".V", ".CN", ".NE")
CHECK_LISTING = ("No exchange in the file: if this is a Canadian listing, add .TO (TSX), .V (TSX Venture) or .NE "
                 "(Cboe Canada) to the symbol in the CSV and preview again, so its price can be found.")


def yahoo_class_share(symbol: str) -> str:
    """Brokers write share classes with a dot (BRK.B, CTC.A); Yahoo uses a dash (BRK-B, CTC-A)."""
    return symbol.replace(".", "-")


def questrade_symbol(symbol: str) -> str:
    """Yahoo's ticker for a Questrade symbol: "SHOP.TO" stays, "ABC.VN" -> "ABC.V", "DLR.U.TO" -> "DLR-U.TO"."""
    upper = symbol.upper()
    base, dot, suffix = upper.rpartition(".")
    if dot and suffix in QUESTRADE_SUFFIX:
        return yahoo_class_share(base) + QUESTRADE_SUFFIX[suffix]
    return yahoo_class_share(upper)


def listed_symbol(symbol: str, exchange: str = "") -> str:
    """Yahoo's ticker for a bare broker symbol ("XEQT", "CTC.A") and an optional exchange name ("TSX")."""
    upper = questrade_symbol(symbol)  # also keeps a suffix the file already has ("XEQT.TO")
    if upper.endswith(CANADIAN_SUFFIXES):
        return upper
    suffix = EXCHANGE_SUFFIX.get(_header_key(exchange)) if exchange else None
    return upper + suffix if suffix else upper


# A CAD row with no exchange (Wealthsimple's export has none) is almost always a TSX listing ("XEQT", "T" for Telus,
# "L" for Loblaw), but the bare ticker is a US one, priced in USD or not at all. So the preview asks the price source
# whether "<symbol>.TO" exists and uses it when it does; otherwise the row keeps CHECK_LISTING. Answers are cached.
TSX_LOOKUPS_PER_FILE = 40  # each is one Yahoo request; a file with more unknown tickers keeps the note for the rest
TSX_LOOKUP_SECONDS = 15
TSX_FOUND_TTL = 24 * 3600
TSX_MISSING_TTL = 600  # short: Yahoo failing looks the same as "no such ticker"
TSX_CACHE_SIZE = 5000
_tsx_cache: dict[str, tuple[bool, float]] = {}  # {"XEQT.TO": (found, expires at (monotonic))}


async def resolve_tsx_listings(rows: list["ImportRow"]) -> None:
    """Give rows marked with a `tsx_candidate` that ticker when the price source knows it (see above)."""
    candidates: dict[str, list[ImportRow]] = {}
    for row in rows:
        if row.status == "ok" and row.tsx_candidate:
            candidates.setdefault(row.tsx_candidate, []).append(row)
    if not candidates:
        return

    now = clock.monotonic()
    found, ask = {}, []
    for ticker in candidates:
        cached = _tsx_cache.get(ticker)
        if cached and cached[1] > now:
            found[ticker] = cached[0]
        elif len(ask) < TSX_LOOKUPS_PER_FILE:
            ask.append(ticker)
    if ask:
        try:
            quotes = await asyncio.wait_for(asset_services.get_latest_stock_quotes(ask), TSX_LOOKUP_SECONDS)
        except Exception as exc:  # slow or down: the rows keep their note, nothing else changes
            log.warning("TSX listing lookup failed: %r", exc)
            quotes = None
        if quotes is not None:
            for ticker in ask:
                found[ticker] = ticker in quotes
                _tsx_cache[ticker] = (found[ticker], now + (TSX_FOUND_TTL if found[ticker] else TSX_MISSING_TTL))
            while len(_tsx_cache) > TSX_CACHE_SIZE:
                _tsx_cache.pop(next(iter(_tsx_cache)))

    for ticker, its_rows in candidates.items():
        if not found.get(ticker):
            continue
        for row in its_rows:
            row.symbol = ticker
            row.notes = [note for note in row.notes if note != CHECK_LISTING]
            row.notes.append(f"No exchange in the file: it's a CAD trade, so it was matched to the TSX listing "
                             f"{ticker}.")


# ---------------------------------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class ImportRow:
    line: int
    date: datetime | None = None
    date_only: bool = False
    action: str | None = None
    asset_type: str | None = None
    symbol: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    currency: str | None = None
    account_type: str | None = None
    coin_id: str | None = None
    status: str = "ok"
    notes: list[str] = field(default_factory=list)
    tsx_candidate: str | None = None  # "XEQT.TO" for a CAD row with no exchange (see resolve_tsx_listings)

    def as_json(self) -> dict:
        """The row as the preview's JSON."""
        return {
            "line": self.line,
            "date": self.date.replace(tzinfo=timezone.utc).isoformat() if self.date else None,
            "date_only": self.date_only,
            "action": self.action,
            "asset_type": self.asset_type,
            "symbol": self.symbol,
            "quantity": float(self.quantity) if self.quantity is not None else None,
            "price": float(self.price) if self.price is not None else None,
            "currency": self.currency,
            "account_type": self.account_type,
            "coin_id": self.coin_id,
            "status": self.status,
            "message": " ".join(self.notes) or None,
        }


ACTIONS = {"BUY": "BUY", "B": "BUY", "BOUGHT": "BUY", "PURCHASE": "BUY", "SELL": "SELL", "S": "SELL", "SOLD": "SELL"}
ASSET_TYPES = {"stock": "stock", "stocks": "stock", "etf": "stock", "equity": "stock", "share": "stock",
               "shares": "stock", "crypto": "crypto", "cryptocurrency": "crypto", "coin": "crypto"}


def clean_trade(row: ImportRow, raw: dict, default_account: str | None, decimal_comma: bool = False,
                strict_account: bool = True, now: datetime | None = None,
                day_first: bool | None = None) -> ImportRow:
    """
    Validate one trade the way POST /transactions would, filling `row` in place (raises RowError). `raw` holds the
    cells (date, action, asset_type, symbol, quantity, price, currency, account_type, coin_id). Both the preview
    and the final import go through here, so the server never trusts what the browser sends back.
    `strict_account`: an account type we don't know is an error (Zenith's own file) rather than a note.
    `day_first`: how the file writes "1/9/2024" (see slash_date_order).
    """
    row.date, row.date_only = parse_trade_date(raw.get("date"), now, day_first)

    action = clean_cell(raw.get("action")).upper()
    if action not in ACTIONS:
        raise RowError(f"Action must be BUY or SELL, not \"{_short(action)}\"" if action else "Missing action (BUY or SELL)")
    row.action = ACTIONS[action]

    symbol = clean_cell(raw.get("symbol"))
    if not symbol:
        raise RowError("Missing symbol")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise RowError(f"Symbol \"{_short(symbol)}\" isn't a ticker")

    asset_type = clean_cell(raw.get("asset_type")).lower()
    if not asset_type:
        if clean_cell(raw.get("coin_id")):
            asset_type = "crypto"
        elif symbol.upper() in KNOWN_CRYPTO:
            # "BTC" without a type could be the coin or the ETF of that name: never guess which
            raise RowError(f"{_short(symbol.upper(), 12)} could be a crypto or a stock: add an asset_type column "
                           "(stock or crypto) to say which")
        else:
            asset_type = "stock"
    if asset_type not in ASSET_TYPES:
        raise RowError(f"Asset type must be stock or crypto, not \"{_short(asset_type)}\"")
    row.asset_type = ASSET_TYPES[asset_type]
    # same casing as trades logged from search: coins are their lowercase CoinGecko symbol, stocks are uppercase
    row.symbol = symbol.lower() if row.asset_type == "crypto" else symbol.upper()

    quantity = parse_number(raw.get("quantity"), "Quantity", decimal_comma)
    if quantity is None:
        raise RowError("Missing quantity")
    quantity = abs(quantity)  # exports often write sells as negative quantities
    if quantity > Decimal(str(MAX_QUANTITY)):  # before as_quantity: 1e20 can't be rounded to 10 decimals
        raise RowError("Quantity is too large")
    quantity = as_quantity(quantity)
    if quantity < Decimal(str(MIN_AMOUNT)):
        raise RowError("Quantity must be greater than 0")
    row.quantity = quantity

    price = parse_number(raw.get("price"), "Price", decimal_comma)
    if price is None:
        raise RowError("Missing price")
    price = abs(price)
    if price < Decimal(str(MIN_AMOUNT)):
        raise RowError("Price must be greater than 0")
    if price > Decimal(str(MAX_PRICE)):
        raise RowError("Price is too large")
    row.price = price

    currency = clean_cell(raw.get("currency")).upper()
    if not currency:
        raise RowError("Missing currency (CAD, USD or EUR)")
    if currency not in SUPPORTED_CURRENCIES:
        raise RowError(f"Prices in {_short(currency, 8)} aren't supported yet (CAD, USD or EUR only)")
    row.currency = currency

    account = map_account_type(raw.get("account_type"))
    if account == UNKNOWN_ACCOUNT:
        if strict_account:
            raise RowError(f"Account \"{_short(clean_cell(raw.get('account_type')))}\" isn't one of "
                           "TFSA, RRSP, FHSA, RESP or NON_REGISTERED")
        row.notes.append(f"Zenith has no \"{_short(clean_cell(raw.get('account_type')))}\" account type, so "
                         + ("the default account was used." if default_account else "the account was left unset."))
        account = None
    row.account_type = account or default_account

    coin_id = clean_cell(raw.get("coin_id")).lower()
    if coin_id and row.asset_type == "crypto":
        if not COIN_ID_PATTERN.fullmatch(coin_id):
            raise RowError(f"coin_id \"{_short(coin_id)}\" isn't a CoinGecko id")
        row.coin_id = coin_id
    return row


# ---------------------------------------------------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------------------------------------------------
def _header_key(text) -> str:
    """"Transaction Date" -> "transaction_date", "Account #" -> "account"; case, spaces and punctuation ignored."""
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").replace("﻿", "").strip().lower()).strip("_")


# For each format: our name -> the header names accepted for it (already as _header_key gives them)
COLUMNS = {
    "zenith": {
        "date": ["date", "datetime", "created_at", "trade_date", "transaction_date", "time"],
        "action": ["action", "side", "transaction_type"],
        "asset_type": ["asset_type", "type", "asset_class"],
        "symbol": ["symbol", "ticker"],
        "quantity": ["quantity", "qty", "shares", "units"],
        "price": ["price", "unit_price", "price_of_one", "price_per_unit"],
        "currency": ["currency", "ccy"],
        "account_type": ["account_type", "account"],
        "coin_id": ["coin_id", "coingecko_id"],
    },
    "wealthsimple": {
        "date": ["transaction_date", "effective_date", "trade_date", "date"],
        "account_type": ["account_type"],
        "activity_type": ["activity_type", "transaction_type", "type"],
        "activity_sub_type": ["activity_sub_type", "sub_type", "subtype"],
        "symbol": ["symbol", "ticker"],
        "exchange": ["exchange", "listing_exchange", "primary_exchange", "market"],
        "currency": ["currency"],
        "quantity": ["quantity", "qty"],
        "price": ["unit_price", "price"],
        "net_amount": ["net_cash_amount", "net_amount", "amount"],
        # the currency of the cash that moved, when a layout gives it apart from the trade's own
        "net_currency": ["net_cash_currency", "net_cash_amount_currency", "net_amount_currency", "cash_currency",
                         "account_currency"],
        "description": ["description"],
    },
    "questrade": {
        "date": ["transaction_date", "trade_date", "date"],
        "action": ["action"],
        "symbol": ["symbol"],
        "quantity": ["quantity"],
        "price": ["price"],
        "currency": ["currency"],
        "account_type": ["account_type"],
        "net_amount": ["net_amount"],
    },
}
REQUIRED = {
    "zenith": ["date", "action", "symbol", "quantity", "price", "currency"],
    "wealthsimple": ["date", "activity_type", "symbol", "quantity", "currency"],
    "questrade": ["date", "action", "symbol", "quantity", "price", "currency"],
}


def _column_map(headers: list[str], fmt: str) -> dict[str, int]:
    """{column name: index} for the columns of format `fmt` found among the headers (by their aliases)."""
    keys = [_header_key(h) for h in headers]
    found = {}
    for name, aliases in COLUMNS[fmt].items():
        for alias in aliases:
            if alias in keys:
                found[name] = keys.index(alias)
                break
    return found


def detect_format(headers: list[str]) -> str | None:
    """Which format these headers are (wealthsimple, questrade or zenith), or None."""
    keys = set(_header_key(h) for h in headers)
    if "activity_type" in keys and keys & {"unit_price", "net_cash_amount"}:
        return "wealthsimple"
    if "action" in keys and "transaction_date" in keys and keys & {"settlement_date", "gross_amount", "net_amount",
                                                                    "commission", "activity_type"}:
        return "questrade"
    if not set(REQUIRED["zenith"]) - set(_column_map(headers, "zenith")):
        return "zenith"
    return None


def _missing(headers: list[str], fmt: str) -> list[str]:
    """The required columns of `fmt` the headers don't have."""
    found = _column_map(headers, fmt)
    missing = [name for name in REQUIRED[fmt] if name not in found]
    if fmt == "wealthsimple" and "price" not in found and "net_amount" not in found:
        missing.append("unit_price")
    return missing


@dataclass
class ParsedFile:
    """A parsed file: its format, every row and how many non-trade rows were skipped."""
    format: str
    rows: list[ImportRow]
    skipped_non_trades: int


def _is_footer(cells: list[str]) -> bool:
    """Whether a line is the export's footer rather than a trade."""
    # Wealthsimple ends its export with a line like "As of 2026-01-18 13:19 GMT-05:00"
    first = next((c.strip() for c in cells if c and c.strip()), "")
    return first.lower().startswith("as of")


def parse_csv(text: str, fmt: str = "auto", default_account: str | None = None,
              now: datetime | None = None) -> ParsedFile:
    """Read a whole file into rows (each "ok" or "error"; duplicates are marked later). Raises FileError."""
    if len(text) > MAX_CSV_BYTES or len(text.encode("utf-8", "surrogatepass")) > MAX_CSV_BYTES:
        raise FileError("This file is larger than 2 MB. Split it into smaller files (e.g. one per year) and import "
                        "them one at a time.", status_code=413)
    text = text.lstrip("﻿")
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    # spreadsheets set to French, German... save CSV with ";" between cells and a decimal comma
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)

    header, chosen, start = None, None, []
    try:
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            start.append(cells)
            found = detect_format(cells) if fmt == "auto" else (fmt if not _missing(cells, fmt) else None)
            if found:
                header, chosen = cells, found
                break
            if len(start) >= 10:  # the header is at the top; don't read a whole unknown file looking for it
                break
    except csv.Error:
        raise FileError("This file isn't a CSV we can read.")

    if header is None:
        if fmt == "auto" or not start:
            raise FileError("We couldn't recognise this file. Choose its format (Zenith template, Wealthsimple or "
                            "Questrade) or start from the Zenith template.")
        raise FileError(f"This doesn't look like a {FORMAT_LABELS[fmt]} file: no "
                        f"{', '.join(_missing(start[0], fmt))} column. Check the format you picked.")

    columns = _column_map(header, chosen)
    parse_row = {"zenith": _zenith_row, "wealthsimple": _wealthsimple_row, "questrade": _questrade_row}[chosen]
    lines = []  # (line number, cells) of every row with something in it
    try:
        for cells in reader:
            if not any(c.strip() for c in cells) or _is_footer(cells):
                continue
            if len(lines) >= MAX_ROWS:
                raise FileError(f"This file has more than {MAX_ROWS:,} rows. Split it into smaller files (e.g. one "
                                "per year) and import them one at a time.")
            lines.append((reader.line_num, cells))
    except csv.Error:
        raise FileError(f"Line {reader.line_num} of this file can't be read (check its quotes).")

    date_at = columns["date"]
    options = RowOptions(default_account, delimiter == ";", now,
                         slash_date_order(cells[date_at] for _, cells in lines if date_at < len(cells)))
    rows, skipped = [], 0
    for line, cells in lines:
        cell = lambda name: cells[columns[name]] if name in columns and columns[name] < len(cells) else ""  # noqa: E731
        row = ImportRow(line=line)
        try:
            if parse_row(row, cell, options) is None:
                skipped += 1
                continue
        except RowError as err:
            _row_failed(row, str(err), cell)
        except (ValueError, ArithmeticError):  # a cell nobody thought of: that row is a problem, not the file
            log.warning("Unexpected error reading line %s of a %s import", line, chosen, exc_info=True)
            _row_failed(row, "This row couldn't be read: check its numbers and date.", cell)
        rows.append(row)
    return ParsedFile(chosen, rows, skipped)


def _row_failed(row: ImportRow, message: str, cell) -> None:
    """Marks a row as an error with `message` (and keeps the cell that caused it)."""
    row.status = "error"
    row.notes = [message]
    row.tsx_candidate = None
    row.symbol = row.symbol or (clean_cell(cell("symbol"))[:32] or None)


@dataclass
class RowOptions:
    """Settings that apply to every row of one file."""
    default_account: str | None
    decimal_comma: bool
    now: datetime | None
    day_first: bool | None  # see slash_date_order


def _clean(row, raw, options: RowOptions, strict_account: bool):
    return clean_trade(row, raw, options.default_account, options.decimal_comma, strict_account=strict_account,
                       now=options.now, day_first=options.day_first)


def _zenith_row(row, cell, options: RowOptions):
    raw = {name: cell(name) for name in COLUMNS["zenith"]}
    return _clean(row, raw, options, strict_account=True)


NET_PRICE_NOTE = "Price worked out from the net amount, so it includes any commission."


def _price_from_net(net: Decimal, quantity: Decimal) -> Decimal:
    """The unit price from a net amount and quantity (abs), or a RowError when it can't be worked out."""
    try:
        return abs(net) / abs(quantity)
    except ArithmeticError:  # 1e999990 / 1e-999990 overflows
        raise RowError("The price couldn't be worked out from the net amount: add the unit price to this row")


FX_RATE = re.compile(r"(?i)\bfx\s*rate")


def _wealthsimple_action(kind: str, sub: str) -> str | None:
    """BUY / SELL from Wealthsimple's activity type and sub-type ("Trade" + "BUY", "CRYPTO_BUY"...), else None."""
    if kind in ("BUY", "SELL"):
        return kind
    if "TRADE" in kind or "CRYPTO" in kind:
        for text in (sub, kind):
            if "BUY" in text:
                return "BUY"
            if "SELL" in text:
                return "SELL"
    return None


def _wealthsimple_row(row, cell, options: RowOptions):
    """None for activity that isn't a buy or sell (dividends, deposits, fees, transfers...)."""
    kind = clean_cell(cell("activity_type")).upper()
    sub = clean_cell(cell("activity_sub_type")).upper()
    action = _wealthsimple_action(kind, sub)
    if action is None:
        return None

    account_text = clean_cell(cell("account_type"))
    symbol = clean_cell(cell("symbol"))
    exchange = clean_cell(cell("exchange"))
    currency = clean_cell(cell("currency")).upper()
    converted = bool(FX_RATE.search(clean_cell(cell("description"))))  # "Bought ..., FX Rate: 1.38": a foreign listing
    # Crypto: the "Crypto" account of older exports, a crypto activity type, or a well-known coin traded in CAD with no
    # exchange and no currency conversion (Wealthsimple's crypto is bought in CAD; "DASH" in USD is DoorDash)
    is_crypto = ("crypto" in account_text.lower() or "CRYPTO" in kind or "CRYPTO" in sub
                 or (symbol.upper() in KNOWN_CRYPTO and currency == "CAD" and not exchange and not converted))

    quantity = parse_number(cell("quantity"), "Quantity", options.decimal_comma)
    price = parse_number(cell("price"), "Price", options.decimal_comma)
    note = None
    if not price and quantity:  # no unit price on the row: work it out from the cash that moved
        net = parse_number(cell("net_amount"), "Net amount", options.decimal_comma)
        if net:
            # the cash has to be in the row's currency, or the price would be in the wrong one
            net_currency = clean_cell(cell("net_currency")).upper()
            if (net_currency and net_currency != currency) or (converted and currency != "CAD"):
                raise RowError("The net amount is in another currency than the trade and there's no unit price: "
                               "add the unit price to this row")
            price, note = _price_from_net(net, quantity), NET_PRICE_NOTE

    if not is_crypto and symbol:
        symbol = listed_symbol(symbol, exchange)
        if currency == "CAD" and not symbol.endswith(CANADIAN_SUFFIXES):
            row.notes.append(CHECK_LISTING)
            if not converted and not exchange:
                row.tsx_candidate = symbol + ".TO"
    raw = {"date": cell("date"), "action": action, "asset_type": "crypto" if is_crypto else "stock",
           "symbol": symbol, "quantity": quantity, "price": price, "currency": currency,
           "account_type": account_text}
    _clean(row, raw, options, strict_account=False)
    if note:
        row.notes.append(note)
    return row


def _questrade_row(row, cell, options: RowOptions):
    """None for anything but Buy / Sell (dividends, deposits, FX conversions, interest...)."""
    action = clean_cell(cell("action")).upper()
    if action not in ("BUY", "SELL"):
        return None
    quantity = parse_number(cell("quantity"), "Quantity", options.decimal_comma)
    price = parse_number(cell("price"), "Price", options.decimal_comma)
    note = None
    if not price and quantity:
        net = parse_number(cell("net_amount"), "Net amount", options.decimal_comma)
        if net:  # Questrade's amounts are all in the row's Currency
            price, note = _price_from_net(net, quantity), NET_PRICE_NOTE

    symbol = clean_cell(cell("symbol"))
    currency = clean_cell(cell("currency")).upper()
    if symbol:
        symbol = questrade_symbol(symbol)
        if currency == "CAD" and not symbol.endswith(CANADIAN_SUFFIXES):
            row.notes.append(CHECK_LISTING)
    raw = {"date": cell("date"), "action": action, "asset_type": "stock", "symbol": symbol, "quantity": quantity,
           "price": price, "currency": currency, "account_type": cell("account_type")}
    _clean(row, raw, options, strict_account=False)
    if note:
        row.notes.append(note)
    return row


# ---------------------------------------------------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------------------------------------------------
SAME_PRICE = Decimal("0.0001")  # relative: the same trade, typed in the same currency
# Relative, when the file and the saved trade are in different currencies: the CAD price was converted at the rate
# of the trade's date (or of the day it was saved), compared here at today's, which may be years apart. Symbol,
# action, time and quantity already have to match.
CROSS_CURRENCY_PRICE = Decimal("0.25")


def _close(a: Decimal, b: Decimal, tolerance: Decimal) -> bool:
    return abs(a - b) <= max(abs(a), abs(b)) * tolerance + Decimal("1e-10")


# A file that only has a day matches a trade saved at any time of that day in any time zone from UTC (Europe) to
# Pacific time: from 00:00 UTC to 08:00 UTC the next morning. A trade logged at 9 pm in Toronto on Jan 14 is saved
# as Jan 15 02:00 UTC, and is still the Jan 14 row of the broker's file.
DATE_ONLY_MATCH = timedelta(hours=32)


def _day_window(row: ImportRow) -> tuple[datetime, datetime]:
    start = datetime.combine(row.date.date(), time())
    return start, start + DATE_ONLY_MATCH


def _same_time(row: ImportRow, saved: datetime) -> bool:
    """Whether a saved trade's time matches the row (the same day for a day-only row, else the same minute)."""
    if row.date_only:
        start, end = _day_window(row)
        return start <= saved < end
    return saved.replace(second=0, microsecond=0) == row.date.replace(second=0, microsecond=0)


def _same_price(row: ImportRow, trade, rates: dict | None) -> bool:
    """Whether a saved trade's price matches the row's, in the currency it was typed in when possible."""
    typed = (str(trade.currency_entered).upper()
             if trade.price_entered is not None and trade.currency_entered else None)
    if typed == row.currency:
        return _close(row.price, Decimal(str(trade.price_entered)), SAME_PRICE)
    saved_cad = Decimal(str(trade.price_of_one))
    if row.currency == "CAD":
        return _close(row.price, saved_cad, SAME_PRICE if typed in (None, "CAD") else CROSS_CURRENCY_PRICE)
    if rates is None:
        return False
    row_cad = row.price / Decimal(str(get_conversion_factor(rates, row.currency)))
    return _close(row_cad, saved_cad, CROSS_CURRENCY_PRICE)


DUPLICATE_NOTE = "Already in your trades, so it's skipped unless you include it."


def mark_duplicates(rows: list[ImportRow], existing, rates: dict | None) -> None:
    """
    Mark rows matching a trade the user already has (same symbol, action and minute, or day when the file only has
    a day, see DATE_ONLY_MATCH; same quantity; same price) as "duplicate". Each saved trade matches one row at most,
    so a file with two identical buys against one saved buy still has one to import. `existing` are saved trades
    (anything with id, symbol, action, created_at, quantity, price_of_one, price_entered, currency_entered).

    Saved trades are indexed by symbol, action and UTC day, so each row only looks at the trades of its own day (and
    the next, for a day-only row): fast with thousands of rows against tens of thousands of trades.
    """
    by_key: dict[tuple, list] = {}
    for trade in existing:
        by_key.setdefault((str(trade.symbol), str(trade.action), trade.created_at.date()), []).append(trade)
    used = set()
    for row in rows:
        if row.status != "ok":
            continue
        day = row.date.date()
        days = (day, day + timedelta(days=1)) if row.date_only else (day,)
        match = next((trade for d in days for trade in by_key.get((row.symbol, row.action, d), ())
                      if trade.id not in used and _same_time(row, trade.created_at)
                      and as_quantity(trade.quantity) == row.quantity and _same_price(row, trade, rates)), None)
        if match is not None:
            used.add(match.id)
            row.status = "duplicate"
            row.notes.insert(0, DUPLICATE_NOTE)


# ---------------------------------------------------------------------------------------------------------------------
# Same-day order and overselling (the preview replays the ledger the way the import will)
# ---------------------------------------------------------------------------------------------------------------------
def place_date_only_sells(rows: list[ImportRow], existing) -> None:
    """
    A file's sell with only a day is stored at DATE_ONLY_HOUR UTC. If a buy of the same symbol was logged later that
    same (UTC) day, by hand or with a time in the file, the sell moves to just after it: the file can't say which came
    first, and selling first would look like selling shares that weren't owned yet.
    """
    latest_buy: dict[tuple, datetime] = {}

    def saw(symbol, moment):
        """Remembers the latest buy of a symbol on a day."""
        key = (symbol, moment.date())
        if key not in latest_buy or moment > latest_buy[key]:
            latest_buy[key] = moment

    for trade in existing:
        if str(trade.action) == "BUY":
            saw(str(trade.symbol), trade.created_at)
    for row in rows:
        if row.status == "ok" and row.action == "BUY" and not row.date_only:
            saw(row.symbol, row.date)
    for row in rows:
        if row.status != "ok" or row.action != "SELL" or not row.date_only:
            continue
        latest = latest_buy.get((row.symbol, row.date.date()))
        if latest is not None and latest >= row.date:
            end_of_day = datetime.combine(row.date.date(), time(23, 59, 59))
            row.date = max(row.date, min(latest + timedelta(seconds=1), end_of_day))


def _amount(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def mark_oversells(rows: list[ImportRow], existing) -> None:
    """
    Replay each symbol's saved trades plus the file's "ok" rows in the order the import will (date, then buys before
    sells at the same moment, like LEDGER_ORDER) and turn every row that would sell more than was owned into an error,
    so the preview never says "Ready" for an import that would be refused. A row is also an error when it sells
    before a saved sell and leaves that one short. Rows marked here are left out of the rest of the replay.
    """
    symbols = {row.symbol for row in rows if row.status == "ok"}
    events: dict[str, list] = {symbol: [] for symbol in symbols}
    for trade in existing:
        symbol = str(trade.symbol)
        if symbol in events:
            events[symbol].append((trade.created_at, str(trade.action), as_quantity(trade.quantity), None))
    for row in rows:
        if row.status == "ok":
            events[row.symbol].append((row.date, row.action, row.quantity, row))

    for symbol, its_events in events.items():
        name = symbol.upper()
        its_events.sort(key=lambda event: (event[0], event[1]))  # "BUY" < "SELL"
        owned = Decimal(0)
        applied = []  # [(file sell row, how much it took off)] in date order
        for moment, action, quantity, row in its_events:
            if action == "BUY":
                owned += quantity
                continue
            if row is not None:
                if quantity > owned + sell_tolerance(owned):
                    row.status = "error"
                    row.notes.insert(0, f"This sells {_amount(quantity)} {name}, but you'd only own "
                                        f"{_amount(owned)} then (your saved trades plus this file's earlier rows), "
                                        "so it can't be imported. Check the file's earlier buys and their dates.")
                    continue
                left = max(Decimal(0), owned - quantity)
                applied.append((row, owned - left))
                owned = left
                continue
            # a saved sell: if the file's earlier sells leave it short, the latest of them can't be imported
            while quantity > owned + sell_tolerance(owned) and applied:
                culprit, took = applied.pop()
                culprit.status = "error"
                culprit.notes.insert(0, f"Importing this would leave your saved {name} sell on "
                                        f"{moment.date().isoformat()} selling more than you owned, so it can't be "
                                        "imported. Check this file's sells and their dates.")
                owned += took
            owned = max(Decimal(0), owned - quantity)


def check_against_saved(rows: list[ImportRow], existing, rates: dict | None) -> None:
    """Everything the preview checks against the user's saved trades, in order (CPU only: run it in a thread)."""
    existing = list(existing)
    mark_duplicates(rows, existing, rates)
    place_date_only_sells(rows, existing)
    mark_oversells(rows, existing)


def summarize(parsed: ParsedFile) -> dict:
    """How many rows are ready, duplicates or errors, and how many lines were skipped."""
    counts = {"ok": 0, "duplicate": 0, "error": 0}
    for row in parsed.rows:
        counts[row.status] += 1
    return {**counts, "skipped_non_trades": parsed.skipped_non_trades}


# ---------------------------------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------------------------------
def _plain(value) -> str:
    """A Decimal/float as plain digits ("0.00000001", not "1E-8"), without trailing zeros."""
    number = Decimal(repr(float(value))) if isinstance(value, float) else Decimal(value)
    text = format(number.normalize(), "f")
    return "0" if text in ("-0", "") else text


def export_row(trade) -> list[str]:
    """One trade as a row of the Zenith template (the price as typed, formula-safe cells)."""
    typed = trade.price_entered is not None and trade.currency_entered
    price = trade.price_entered if typed else trade.price_of_one
    return [csv_safe(cell) for cell in (
        trade.created_at.replace(tzinfo=timezone.utc).isoformat(),
        trade.action,
        trade.asset_type,
        trade.symbol,
        _plain(as_quantity(trade.quantity)),
        _plain(Decimal(repr(float(price)))),
        str(trade.currency_entered).upper() if typed else "CAD",
        trade.account_type or "",
        trade.coin_id or "",
    )]


def write_csv(rows: list[list[str]]) -> str:
    """The template's header and these rows as CSV text."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(rows)
    return out.getvalue()


def template_csv() -> str:
    """The Zenith template with two example rows, for people filling it in by hand."""
    example = datetime.now(timezone.utc).replace(hour=15, minute=30, second=0, microsecond=0) - timedelta(days=30)
    return write_csv([
        [example.date().isoformat(), "BUY", "stock", "AAPL", "10", "189.50", "USD", "TFSA", ""],
        [example.isoformat(), "BUY", "crypto", "btc", "0.05", "85000", "CAD", "NON_REGISTERED", "bitcoin"],
    ])
