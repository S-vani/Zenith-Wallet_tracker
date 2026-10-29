// Pull to refresh's decisions, kept pure for the tests (test/native.test.js).

// the pages that reload their data on "app:refresh" (useRefreshKey); elsewhere a pull does nothing
const REFRESHABLE_PAGES = ["/dashboard", "/holdings", "/transactions"];

// Whether pull to refresh works on this page.
export function canPullToRefresh(pathname) {
    return REFRESHABLE_PAGES.includes(pathname.replace(/\/+$/, ""));
}

// what a completed pull does: "refresh", or "offline" (say so instead of pretending to reload)
export function pullAction({online}) {
    return online ? "refresh" : "offline";
}

// the spinner stays at least this long, so a fast reload still reads as one, and gives up after the longest
// request timeout so it can never spin forever
export const MIN_SPIN_MS = 450;
export const MAX_SPIN_MS = 13000;
