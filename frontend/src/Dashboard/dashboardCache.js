import {getToken} from "../services/api.js";

// Stats + chart for each range, kept in memory for a minute so going back to a range (or to the dashboard) is
// instant. Keys include the session token, so another account signing in on the same tab never sees these.
export const CACHE_MS = 60_000;

const entries = new Map();

export function dashboardKey(range, days, currency) {
    return `${getToken() ?? ""}|${currency}|${range}|${days}`;
}

// The saved entry if it's younger than CACHE_MS, otherwise undefined (read-only, so it's safe during render)
export function readDashboardCache(key, now = Date.now()) {
    const saved = key ? entries.get(key) : undefined;
    return saved && now - saved.at < CACHE_MS ? saved.entry : undefined;
}

export function writeDashboardCache(key, entry, now = Date.now()) {
    entries.set(key, {entry, at: now});
    // only a handful of ranges exist, but drop expired ones so old sessions don't pile up
    for (const [k, saved] of entries) {
        if (now - saved.at >= CACHE_MS) entries.delete(k);
    }
}

export function clearDashboardCache() {
    entries.clear();
}
