import {isNative} from "./platform.js";

// App only: the last successful response of the portfolio screens is kept on the phone, so they still show data
// (under the "You're offline" banner) without a connection, even right after opening the app.
// The website never stores portfolio data in the browser. Cleared on sign out and account deletion.
const PREFIX = "offline:";
const CACHED = ["/dashboard", "/portfolio/history", "/holdings", "/transactions", "/user", "/prices/history"];

const cacheable = (path) => CACHED.some((start) => path === start || path.startsWith(`${start}?`));

export function remember(path, data) {
    if (!isNative || !cacheable(path)) return;
    try {
        localStorage.setItem(PREFIX + path, JSON.stringify(data));
    } catch {
        // storage full: the app simply works online-only for that screen
    }
}

// the saved response, or undefined when there isn't one
export function recall(path) {
    if (!isNative || !cacheable(path)) return undefined;
    try {
        const saved = localStorage.getItem(PREFIX + path);
        return saved === null ? undefined : JSON.parse(saved);
    } catch {
        return undefined;
    }
}

export function forgetAll() {
    if (!isNative) return;
    try {
        Object.keys(localStorage).filter((key) => key.startsWith(PREFIX)).forEach((key) => localStorage.removeItem(key));
    } catch {
        // nothing to clear
    }
}
