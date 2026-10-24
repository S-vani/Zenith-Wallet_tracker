"""
CSV import and export of trades (routes in backend/routes/imports.py).

Export writes Zenith's own template; import reads that template plus Wealthsimple's activities export and
Questrade's account activity export, and turns every row into the same shape a manual trade has. Nothing here
touches the database or a price source: the routes do that, so all of this is plain, testable parsing.

The broker layouts come from their exports as seen in other open-source importers (not from official docs), so
column matching is deliberately loose: case, spaces and punctuation in headers don't matter and a few aliases are
accepted for each column.
"""
import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from backend.schemas.assets import ACCOUNT_TYPES, FUTURE_SKEW, MAX_QUANTITY, MIN_AMOUNT, OLDEST_DATE
from backend.services.asset_services import as_quantity, get_conversion_factor

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_PRICE = 1e9  # same cap as CreateTransaction.price_of_one
SUPPORTED_CURRENCIES = ("CAD", "USD", "EUR")  # what get_conversion_factor knows

FORMATS = ("zenith", "wealthsimple", "questrade")
FORMAT_LABELS = {"zenith": "Zenith template", "wealthsimple": "Wealthsimple", "questrade": "Questrade"}

EXPORT_COLUMNS = ["date", "action", "asset_type", "symbol", "quantity", "price", "currency", "account_type", "coin_id"]

# Broker exports usually only give a day. Noon UTC is that same calendar day everywhere from Vancouver to Europe, so
# the trade shows on the right date for everyone (midnight UTC would show as the evening before in Canada).
DATE_ONLY_HOUR = 12

# Ticker-ish text only: letters, digits and the . - ^ = Yahoo uses. Also keeps formula text out of the database.
SYMBOL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-^=]{0,31}")
COIN_ID_PATTERN = re.compile(r"[a-z0-9-]{1,80}")


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


THOUSANDS = re.compile(r"[-+]?\d{1,3}(,\d{3})+(\.\d*)?")
PLAIN_NUMBER = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def parse_number(value, label: str, decimal_comma: bool = False) -> Decimal | None:
    """
    A number from a cell, or None when it's empty. Accepts "1234.5", "1,234.50", "$12.30", "(5.00)" (accounting
    negative) and, in semicolon-separated files (European spreadsheets), "1,5". Raises RowError otherwise.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise RowError(f"{label} isn't a number")
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise RowError(f"{label} isn't a number")
        return Decimal(repr(float(value)))

    text = clean_cell(value).replace(" ", "").replace(" ", "")
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

    if not PLAIN_NUMBER.fullmatch(text):
        raise RowError(f"{label} \"{_short(value)}\" isn't a number")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise RowError(f"{label} \"{_short(value)}\" isn't a number")
    if not number.is_finite():
        raise RowError(f"{label} isn't a number")
    return -number if negative else number


ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Questrade: "2026-02-17 12:00:00 AM"
AM_PM = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*([AaPp][Mm])")
YMD_SLASH = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})(?:[ T].*)?")
DMY_OR_MDY = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:[ T].*)?")


def _date_only(year: int, month: int, day: int) -> datetime:
    try:
        return datetime(year, month, day, DATE_ONLY_HOUR)
    except ValueError:
        raise RowError("Date isn't a real calendar date")


def parse_trade_date(value, now: datetime | None = None) -> tuple[datetime, bool]:
    """
    (naive UTC datetime, whether the cell only had a day). Dates with an offset are converted to UTC, ones without
    are read as UTC (Zenith's export writes UTC). A day alone is stored at DATE_ONLY_HOUR UTC. Like a manual trade it
    can't be in the future or before 1970 (raises RowError).
    """
    text = clean_cell(value)
    if not text:
        raise RowError("Missing date")
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    date_only = False
    m = AM_PM.fullmatch(text)
    if m:
        day, hour, minute, second, half = m.groups()
        hour, minute, second = int(hour) % 12 + (12 if half.lower() == "pm" else 0), int(minute), int(second or 0)
        if hour == minute == second == 0:  # Questrade writes every trade at "12:00:00 AM": only the day is known
            y, mo, d = map(int, day.split("-"))
            moment, date_only = _date_only(y, mo, d), True
        else:
            moment = datetime.fromisoformat(day).replace(hour=hour, minute=minute, second=second)
    elif ISO_DATE.fullmatch(text):
        y, mo, d = map(int, text.split("-"))
        moment, date_only = _date_only(y, mo, d), True
    elif (m := YMD_SLASH.fullmatch(text)):
        moment, date_only = _date_only(*map(int, m.groups())), True
    elif (m := DMY_OR_MDY.fullmatch(text)):
        # a spreadsheet re-saved the date in its own style; only accept it when it can't be read two ways
        first, second, year = map(int, m.groups())
        if first > 12 >= second:
            day, month = first, second
        elif second > 12 >= first:
            day, month = second, first
        elif first == second:
            day = month = first
        else:
            raise RowError(f"Date \"{_short(text)}\" could be read two ways: use YYYY-MM-DD")
        moment, date_only = _date_only(year, month, day), True
    else:
        try:
            moment = datetime.fromisoformat(text.removesuffix(" UTC"))
        except ValueError:
            raise RowError(f"Date \"{_short(text)}\" isn't a date we can read: use YYYY-MM-DD")
        if moment.tzinfo:
            moment = moment.astimezone(timezone.utc).replace(tzinfo=None)

    if (moment.date() > now.date()) if date_only else (moment > now + FUTURE_SKEW):
        raise RowError("Date is in the future")
    if moment < OLDEST_DATE:
        raise RowError("Date must be after 1970")
    return min(moment, now), date_only


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

    def as_json(self) -> dict:
        return {
            "line": self.line,
            "date": self.date.replace(tzinfo=timezone.utc).isoformat() if self.date else None,
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
                strict_account: bool = True, now: datetime | None = None) -> ImportRow:
    """
    Validate one trade the way POST /transactions would, filling `row` in place (raises RowError). `raw` holds the
    cells (date, action, asset_type, symbol, quantity, price, currency, account_type, coin_id). Both the preview
    and the final import go through here, so the server never trusts what the browser sends back.
    `strict_account`: an account type we don't know is an error (Zenith's own file) rather than a note.
    """
    row.date, row.date_only = parse_trade_date(raw.get("date"), now)

    action = clean_cell(raw.get("action")).upper()
    if action not in ACTIONS:
        raise RowError(f"Action must be BUY or SELL, not \"{_short(action)}\"" if action else "Missing action (BUY or SELL)")
    row.action = ACTIONS[action]

    asset_type = clean_cell(raw.get("asset_type")).lower() or "stock"
    if asset_type not in ASSET_TYPES:
        raise RowError(f"Asset type must be stock or crypto, not \"{_short(asset_type)}\"")
    row.asset_type = ASSET_TYPES[asset_type]

    symbol = clean_cell(raw.get("symbol"))
    if not symbol:
        raise RowError("Missing symbol")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise RowError(f"Symbol \"{_short(symbol)}\" isn't a ticker")
    # same casing as trades logged from search: coins are their lowercase CoinGecko symbol, stocks are uppercase
    row.symbol = symbol.lower() if row.asset_type == "crypto" else symbol.upper()

    quantity = parse_number(raw.get("quantity"), "Quantity", decimal_comma)
    if quantity is None:
        raise RowError("Missing quantity")
    quantity = as_quantity(abs(quantity))  # exports often write sells as negative quantities
    if quantity < Decimal(str(MIN_AMOUNT)):
        raise RowError("Quantity must be greater than 0")
    if quantity > Decimal(str(MAX_QUANTITY)):
        raise RowError("Quantity is too large")
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
    keys = [_header_key(h) for h in headers]
    found = {}
    for name, aliases in COLUMNS[fmt].items():
        for alias in aliases:
            if alias in keys:
                found[name] = keys.index(alias)
                break
    return found


def detect_format(headers: list[str]) -> str | None:
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
    found = _column_map(headers, fmt)
    missing = [name for name in REQUIRED[fmt] if name not in found]
    if fmt == "wealthsimple" and "price" not in found and "net_amount" not in found:
        missing.append("unit_price")
    return missing


@dataclass
class ParsedFile:
    format: str
    rows: list[ImportRow]
    skipped_non_trades: int


def _is_footer(cells: list[str]) -> bool:
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
    rows, skipped = [], 0
    try:
        for cells in reader:
            if not any(c.strip() for c in cells) or _is_footer(cells):
                continue
            if len(rows) + skipped >= MAX_ROWS:
                raise FileError(f"This file has more than {MAX_ROWS:,} rows. Split it into smaller files (e.g. one "
                                "per year) and import them one at a time.")
            cell = lambda name: cells[columns[name]] if name in columns and columns[name] < len(cells) else ""  # noqa: E731
            row = ImportRow(line=reader.line_num)
            try:
                if parse_row(row, cell, default_account, delimiter == ";", now) is None:
                    skipped += 1
                    continue
            except RowError as err:
                row.status = "error"
                row.notes = [str(err)]
                row.symbol = row.symbol or (clean_cell(cell("symbol"))[:32] or None)
            rows.append(row)
    except csv.Error:
        raise FileError(f"Line {reader.line_num} of this file can't be read (check its quotes).")
    return ParsedFile(chosen, rows, skipped)


def _zenith_row(row, cell, default_account, decimal_comma, now):
    raw = {name: cell(name) for name in COLUMNS["zenith"]}
    return clean_trade(row, raw, default_account, decimal_comma, strict_account=True, now=now)


def _wealthsimple_row(row, cell, default_account, decimal_comma, now):
    """None for activity that isn't a buy or sell (dividends, deposits, fees, transfers...)."""
    kind = clean_cell(cell("activity_type")).upper()
    sub = clean_cell(cell("activity_sub_type")).upper()
    if kind in ("BUY", "SELL"):
        action = kind
    elif kind == "TRADE" and ("BUY" in sub or "SELL" in sub):
        action = "BUY" if "BUY" in sub else "SELL"
    else:
        return None

    account_text = clean_cell(cell("account_type"))
    is_crypto = "crypto" in account_text.lower()
    quantity = parse_number(cell("quantity"), "Quantity", decimal_comma)
    price = parse_number(cell("price"), "Price", decimal_comma)
    note = None
    if not price and quantity:  # no unit price on the row: work it out from the cash that moved
        net = parse_number(cell("net_amount"), "Net amount", decimal_comma)
        if net:
            price = abs(net) / abs(quantity)
            note = "Price worked out from the net amount, so it includes any commission."

    symbol = clean_cell(cell("symbol"))
    exchange = clean_cell(cell("exchange"))
    currency = clean_cell(cell("currency")).upper()
    if not is_crypto and symbol:
        symbol = listed_symbol(symbol, exchange)
        if currency == "CAD" and not symbol.endswith(CANADIAN_SUFFIXES):
            row.notes.append(CHECK_LISTING)
    raw = {"date": cell("date"), "action": action, "asset_type": "crypto" if is_crypto else "stock",
           "symbol": symbol, "quantity": quantity, "price": price, "currency": currency,
           "account_type": account_text}
    clean_trade(row, raw, default_account, decimal_comma, strict_account=False, now=now)
    if note:
        row.notes.append(note)
    return row


def _questrade_row(row, cell, default_account, decimal_comma, now):
    """None for anything but Buy / Sell (dividends, deposits, FX conversions, interest...)."""
    action = clean_cell(cell("action")).upper()
    if action not in ("BUY", "SELL"):
        return None
    quantity = parse_number(cell("quantity"), "Quantity", decimal_comma)
    price = parse_number(cell("price"), "Price", decimal_comma)
    note = None
    if not price and quantity:
        net = parse_number(cell("net_amount"), "Net amount", decimal_comma)
        if net:
            price = abs(net) / abs(quantity)
            note = "Price worked out from the net amount, so it includes any commission."

    symbol = clean_cell(cell("symbol"))
    currency = clean_cell(cell("currency")).upper()
    if symbol:
        symbol = questrade_symbol(symbol)
        if currency == "CAD" and not symbol.endswith(CANADIAN_SUFFIXES):
            row.notes.append(CHECK_LISTING)
    raw = {"date": cell("date"), "action": action, "asset_type": "stock", "symbol": symbol, "quantity": quantity,
           "price": price, "currency": currency, "account_type": cell("account_type")}
    clean_trade(row, raw, default_account, decimal_comma, strict_account=False, now=now)
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


def _same_time(row: ImportRow, saved: datetime) -> bool:
    if row.date_only:  # the file only has a day: any time that day (UTC) counts
        return saved.date() == row.date.date()
    return saved.replace(second=0, microsecond=0) == row.date.replace(second=0, microsecond=0)


def _same_price(row: ImportRow, trade, rates: dict | None) -> bool:
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


def mark_duplicates(rows: list[ImportRow], existing, rates: dict | None) -> None:
    """
    Mark rows matching a trade the user already has (same symbol, action and minute, or day when the file only has
    a day; same quantity; same price) as "duplicate". Each saved trade matches one row at most, so a file with two
    identical buys against one saved buy still has one to import.
    """
    by_key: dict[tuple, list] = {}
    for trade in existing:
        by_key.setdefault((str(trade.symbol), str(trade.action)), []).append(trade)
    used = set()
    for row in rows:
        if row.status != "ok":
            continue
        for trade in by_key.get((row.symbol, row.action), []):
            if (trade.id not in used and _same_time(row, trade.created_at)
                    and as_quantity(trade.quantity) == row.quantity and _same_price(row, trade, rates)):
                used.add(trade.id)
                row.status = "duplicate"
                row.notes.insert(0, "Already in your trades, so it's skipped unless you include it.")
                break


def summarize(parsed: ParsedFile) -> dict:
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
