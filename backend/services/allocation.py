"""
Portfolio allocation ("X-ray"): how today's portfolio value splits by asset type, account, holding and listing
currency. Pure maths only; the route (backend/routes/allocation.py) loads the trades and prices.

Every value is quantity x the holding's current price from the same pricing path as /holdings, so the total here
is the dashboard's portfolio value. Holdings with no price are listed in `unpriced` and left out of every group.
"""
from decimal import Decimal

from backend.schemas.assets import ACCOUNT_UNSET
from backend.services import asset_services
from backend.services.asset_services import as_quantity, guess_listing_currency, sell_tolerance

CRYPTO_CURRENCY = "CRYPTO"  # coins have no listing currency of their own (their CAD/USD pair is just a quote)
UNKNOWN_CURRENCY = "OTHER"


def replay_accounts(trades) -> dict[str, dict[str, Decimal]]:
    """
    Quantity of each holding per account, {api_id: {account_type or "UNSET": quantity}}, from trades sorted
    oldest first (LEDGER_ORDER). A buy adds to its own account. A sell takes from its own account first.

    People don't always tag every trade (e.g. untagged buys, then a sell marked TFSA), so a sell can ask an account
    for more than that account holds. The shortfall is then taken from the same holding's other accounts: "not set"
    first (most likely where the untagged shares really were), then the largest account, ties by name. No account
    ever goes negative, and the per-account quantities always add up to the holding's quantity from apply_trade
    (a sell of everything, within sell_tolerance, empties every account like it removes the holding).
    """
    positions: dict[str, dict[str, Decimal]] = {}
    for t in trades:
        api_id = str(t.api_id)
        account = t.account_type or ACCOUNT_UNSET
        qty = as_quantity(t.quantity)

        if str(t.action) == "BUY":
            accounts = positions.setdefault(api_id, {})
            accounts[account] = accounts.get(account, Decimal(0)) + qty
            continue

        accounts = positions.get(api_id)
        if not accounts:  # nothing held (apply_trade ignores it too; the ledger check stops real oversells)
            continue
        total = sum(accounts.values())
        if qty >= total - sell_tolerance(total):
            del positions[api_id]  # sold out, like apply_trade
            continue

        own = accounts.get(account, Decimal(0))
        taken = min(qty, own)
        if account in accounts:
            accounts[account] = own - taken
        rest = qty - taken
        others = sorted((k for k in accounts if k != account),
                        key=lambda k: (k != ACCOUNT_UNSET, -accounts[k], k))
        for key in others:
            if rest <= 0:
                break
            taken = min(rest, accounts[key])
            accounts[key] -= taken
            rest -= taken
        for key in [k for k, q in accounts.items() if q <= 0]:
            del accounts[key]
    return positions


def listing_currency(api_id: str, asset_type: str) -> str:
    """
    A holding's listing currency without asking Yahoo again: pricing a stock already looked it up (and cached it in
    asset_services), and otherwise it is guessed from the ticker's suffix. Pence ("GBp") count as GBP exposure.
    """
    if asset_type == "crypto":
        return CRYPTO_CURRENCY
    # read at call time (not imported by name) so it's always the cache pricing just filled
    currency = asset_services._symbol_currency_cache.get(api_id) or guess_listing_currency(api_id)
    return str(currency).upper() if currency else UNKNOWN_CURRENCY


def _group(values: dict[str, float], total: float) -> list[dict]:
    """[{key, value, weight}] sorted by value (largest first, then key), dropping empty groups."""
    rows = [{"key": key, "value": value, "weight": value / total if total > 0 else 0.0}
            for key, value in values.items() if value > 0]
    return sorted(rows, key=lambda r: (-r["value"], r["key"]))


def build_allocation(holdings: dict, accounts: dict, prices: dict, currency: str) -> dict:
    """
    `holdings` is get_holdings_at_time's {api_id: {quantity, type, ...}}, `accounts` replay_accounts' output for the
    same trades and `prices` {api_id: current price in the user's currency, None = no price}.
    """
    unpriced = sorted(api_id for api_id in holdings if prices.get(api_id) is None)
    by_type: dict[str, float] = {}
    by_account: dict[str, float] = {}
    by_currency: dict[str, float] = {}
    rows = []

    for api_id, data in holdings.items():
        price = prices.get(api_id)
        if price is None:
            continue
        price = float(price)
        quantity = float(data["quantity"])
        value = price * quantity
        asset_type = str(data["type"])
        rows.append({"symbol": api_id, "asset_type": asset_type, "value": value})
        by_type[asset_type] = by_type.get(asset_type, 0.0) + value
        code = listing_currency(api_id, asset_type)
        by_currency[code] = by_currency.get(code, 0.0) + value

        split = accounts.get(api_id) or {ACCOUNT_UNSET: Decimal(repr(quantity))}
        held = sum(split.values())
        for account, qty in split.items():
            # this account's share of the holding's value, so the accounts add up to exactly the holding
            share = value * float(qty / held) if held > 0 else 0.0
            by_account[account] = by_account.get(account, 0.0) + share

    total = sum(row["value"] for row in rows)
    for row in rows:
        row["weight"] = row["value"] / total if total > 0 else 0.0
    rows.sort(key=lambda r: (-r["value"], r["symbol"]))

    return {
        "currency": (currency or "CAD").upper(),
        "total": total,
        "unpriced": unpriced,
        "by_asset_type": _group(by_type, total),
        "by_account": _group(by_account, total),
        "by_holding": [row for row in rows if row["value"] > 0],
        "by_currency": _group(by_currency, total),
    }
