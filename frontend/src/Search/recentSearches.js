// The last assets opened from Search, shown as "Recent" before the next search. Kept in this browser / phone only
// (localStorage), newest first, symbols only: prices are always fetched fresh.
const KEY = "recentSearches";
const MAX = 8;

// [{symbol, type}], newest first; [] when nothing is saved or storage can't be read.
export function loadRecent() {
    try {
        const list = JSON.parse(localStorage.getItem(KEY) ?? "[]");
        return Array.isArray(list)
            ? list.filter((r) => typeof r?.symbol === "string" && (r.type === "stock" || r.type === "crypto"))
            : [];
    } catch {
        return [];
    }
}

// Puts an asset first (once) and returns the new list.
export function rememberRecent(symbol, type) {
    const upper = String(symbol).toUpperCase();
    const list = [{symbol: upper, type}, ...loadRecent().filter((r) => !(r.symbol === upper && r.type === type))]
        .slice(0, MAX);
    try {
        localStorage.setItem(KEY, JSON.stringify(list));
    } catch {
        // not saved: the list still shows for now
    }
    return list;
}
