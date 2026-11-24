// The holdings list's orders (HoldingsList): by value, today's change, return or symbol. Pure, for the tests.

// How the list can be ordered; unknown values (no price) always go last
export const SORTS = [
    {value: "value", label: "Value", key: (h) => h.current_price},
    {value: "today", label: "Today", key: (h) => h.day_change_pct},
    {value: "return", label: "Return", key: (h) => (h.current_price !== null && h.price_paid > 0
            ? h.current_price / h.price_paid - 1 : null)},
    {value: "name", label: "A–Z", key: null},
];
export const SORT_KEY = "holdingsSort";

// The order saved in this browser / phone, or "value".
export function savedSort() {
    try {
        const saved = localStorage.getItem(SORT_KEY);
        return SORTS.some((s) => s.value === saved) ? saved : "value";
    } catch {
        return "value";
    }
}

// The holdings in the chosen order (biggest number first; A–Z by symbol).
export function sortHoldings(holdings, sort) {
    const option = SORTS.find((s) => s.value === sort) ?? SORTS[0];
    if (!option.key) return [...holdings].sort((a, b) => a.symbol.localeCompare(b.symbol));
    const key = (h) => option.key(h) ?? -Infinity;
    return [...holdings].sort((a, b) => key(b) - key(a) || a.symbol.localeCompare(b.symbol));
}
