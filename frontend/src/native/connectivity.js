import {isNative} from "./platform.js";

// App only: whether the phone is online, and whether the screen shows saved data because the server couldn't be
// reached (timeout, server down, captive Wi-Fi) while the phone still reports a connection. Either one shows the
// banner at the top; <html> gets the "offline" class then, so the CSS moves the page and toasts below it.
// Nothing here runs on the website: the banner isn't mounted there and request() never falls back to saved data.

// replaced (never changed in place) on every update, so useSyncExternalStore can compare snapshots
let snapshot = Object.freeze({online: true, stale: false});

const listeners = new Set();

// The current {online, stale} state.
export function getConnectivity() {
    return snapshot;
}

// listener({online, stale}) on every change; returns an unsubscribe function
export function subscribeConnectivity(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

// Applies a change, sets the <html> class and tells the listeners (app only).
function update(changes) {
    if (!isNative) return;
    const next = {...snapshot, ...changes};
    if (next.online === snapshot.online && next.stale === snapshot.stale) return;
    snapshot = Object.freeze(next);
    document.documentElement.classList.toggle("offline", !next.online || next.stale);
    listeners.forEach((listener) => listener(snapshot));
}

// Whether the phone has a connection.
export function setOnline(online) {
    // coming back online clears "stale": the pages reload (app:refresh) and mark it again if that still fails
    update(online ? {online, stale: false} : {online});
}

// called by request() when it answers with saved data instead of the server's
export function markStale() {
    if (!isNative) return;
    update({stale: true});
    window.dispatchEvent(new Event("app:stale"));
}

// called by request() when the server answered
export function markFresh() {
    if (snapshot.stale) update({stale: false});
}

// Requests in progress, so pull to refresh can spin exactly as long as the reload it started (app only)
let inFlight = 0;
let idleWaiters = [];

// call when a request starts; returns the function to call when it ends (safe to call twice)
export function requestStarted() {
    if (!isNative) return () => {};
    inFlight += 1;
    let ended = false;
    return () => {
        if (ended) return;
        ended = true;
        inFlight -= 1;
        if (inFlight === 0) {
            const waiters = idleWaiters;
            idleWaiters = [];
            waiters.forEach((resolve) => resolve());
        }
    };
}

// resolves once no request is in progress
export function whenRequestsSettle() {
    return inFlight === 0 ? Promise.resolve() : new Promise((resolve) => idleWaiters.push(resolve));
}

// How long a request may take before the app gives up and shows saved data. The market analyst gathers a lot of
// data on the server, and a CSV import of thousands of rows can take a while to check and save (the import also
// sends an id, so a retry after a timeout never imports twice), so they get longer. Changes (POST, PUT, DELETE)
// get a minute: they have no saved copy to fall back on, and giving up early on one the server is still saving
// (a backdated trade waiting on an exchange-rate history) invited a second, duplicate save. 0 = no limit, which is
// what the website keeps.
export function requestTimeout(path, method = "GET") {
    if (!isNative) return 0;
    if (path.startsWith("/transactions/import")) return 120000;
    if (method.toUpperCase() !== "GET") return 60000;
    return path.startsWith("/analyst") ? 45000 : 12000;
}
