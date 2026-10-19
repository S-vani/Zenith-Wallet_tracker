// The password reset token from the emailed link (/reset-password?token=...). The page reads it once and takes it
// out of the address bar, so it isn't left in the browser's history (or synced to other devices with it). This tab
// keeps a copy in sessionStorage until the new password is saved, so a reload still works.

const SAVED_TOKEN_KEY = "resetToken";

export function readSavedToken() {
    try {
        return sessionStorage.getItem(SAVED_TOKEN_KEY);
    } catch {
        return null;
    }
}

// null forgets it (once it's been used)
export function saveToken(token) {
    try {
        if (token) sessionStorage.setItem(SAVED_TOKEN_KEY, token);
        else sessionStorage.removeItem(SAVED_TOKEN_KEY);
    } catch {
        // storage blocked: a reload then needs the emailed link again
    }
}

// "/reset-password?token=abc&x=1#top" -> "/reset-password?x=1#top"
export function withoutParam(path, name) {
    const url = new URL(path, "http://x");
    if (!url.searchParams.has(name)) return path;
    url.searchParams.delete(name);
    return url.pathname + url.search + url.hash;
}

// Swaps this history entry's address for one without ?token=. React Router's state (window.history.state) is kept,
// so Back and Forward still work.
export function removeTokenFromAddressBar() {
    const current = window.location.pathname + window.location.search + window.location.hash;
    const clean = withoutParam(current, "token");
    if (clean !== current) window.history.replaceState(window.history.state, "", clean);
}
