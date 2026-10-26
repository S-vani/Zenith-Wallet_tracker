// Pure maths for the holdings list. /holdings gives totals per position: price_paid = average cost × quantity and
// current_price = latest price × quantity (null when no source has a price), both in the user's currency.

export function isPriced(holding) {
    return holding.current_price !== null && holding.current_price !== undefined;
}

// The average cost pools every account (TFSA, RRSP and non-registered buys together), so it isn't the ACB CRA asks
// for; said wherever it's shown so nobody files with it
export const AVG_COST_NOTE = "Average across all your accounts, not your tax ACB (see Tax report).";

// Average cost of one unit (share / coin), or null when it can't be worked out
export function averageCost(holding) {
    const quantity = Number(holding.quantity);
    const paid = Number(holding.price_paid);
    return quantity > 0 && Number.isFinite(paid) ? paid / quantity : null;
}

// Value and return over the priced holdings only: an unpriced one would otherwise count as worth $0 (−100%).
// The symbols left out come back in `unpriced` so the page can say so.
export function holdingsTotals(holdings) {
    let value = 0;
    let cost = 0;
    const unpriced = [];

    for (const holding of holdings) {
        if (!isPriced(holding)) {
            unpriced.push(String(holding.symbol).toUpperCase());
            continue;
        }
        value += Number(holding.current_price) || 0;
        cost += Number(holding.price_paid) || 0;
    }

    if (unpriced.length === holdings.length) {
        return {value: null, cost: null, gain: null, gainPct: null, unpriced};
    }

    const gain = value - cost;
    return {value, cost, gain, gainPct: cost > 0 ? (gain / cost) * 100 : null, unpriced};
}
