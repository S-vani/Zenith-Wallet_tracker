import {isNative} from "./platform.js";

// App only: whether the phone is online, and whether the screen shows saved data because the server couldn't be
// reached (timeout, server down, captive Wi-Fi) while the phone still reports a connection. Either one shows the
// banner at the top; <html> gets the "offline" class then, so the CSS moves the page and toasts below it.
// Nothing here runs on the website: the banner isn't mounted there and request() never falls back to saved data.

// replaced (never changed in place) on every update, so useSyncExternalStore can compare snapshots
let snapshot = Object.freeze({online: true, stale: false});

const listeners = new Set();

export function getConnectivity() {
    return snapshot;
}

// listener({online, stale}) on every change; returns an unsubscribe function
export function subscribeConnectivity(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

function update(changes) {
    if (!isNative) return;
    const next = {...snapshot, ...changes};
    if (next.online === snapshot.online && next.stale === snapshot.stale) return;
    snapshot = Object.freeze(next);
    document.documentElement.classList.toggle("offline", !next.online || next.stale);
    listeners.forEach((listener) => listener(snapshot));
}

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
// data on the server, so it gets longer. 0 = no limit, which is what the website keeps.
export function requestTimeout(path) {
    if (!isNative) return 0;
    return path.startsWith("/analyst") ? 45000 : 12000;
}
