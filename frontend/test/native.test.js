import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

// The native helpers must be complete no-ops on the website: no plugin calls, no state, no changes to the page.
// The app-only behaviour is tested with platform.js mocked to say "native" (inApp()).

let store;
let classes;
let events;

// like the real localStorage: methods plus the stored keys as own, enumerable properties (Object.keys works)
function fakeStorage(map) {
    const methods = {
        getItem: (k) => (map.has(k) ? map.get(k) : null),
        setItem: (k, v) => map.set(k, String(v)),
        removeItem: (k) => map.delete(k),
    };
    return new Proxy(Object.create(methods), {
        ownKeys: () => [...map.keys()],
        getOwnPropertyDescriptor: (target, k) => (map.has(k)
            ? {enumerable: true, configurable: true, value: map.get(k)}
            : undefined),
    });
}

function inApp() {
    vi.doMock("../src/native/platform.js", () => ({isNative: true, loadPlugin: () => () => Promise.reject(new Error("no plugin"))}));
}

beforeEach(() => {
    vi.resetModules();
    store = new Map();
    classes = new Set();
    events = [];
    vi.stubGlobal("localStorage", fakeStorage(store));
    vi.stubGlobal("document", {
        documentElement: {
            classList: {
                add: (c) => classes.add(c),
                remove: (c) => classes.delete(c),
                toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
                contains: (c) => classes.has(c),
            },
        },
    });
    vi.stubGlobal("window", {dispatchEvent: (e) => events.push(e.type)});
});

afterEach(() => {
    vi.doUnmock("../src/native/platform.js");
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

describe("native helpers on the website", () => {
    it("knows it isn't running in the app", async () => {
        const {isNative} = await import("../src/native/platform.js");
        expect(isNative).toBe(false);
    });

    it("starts without touching the page or the token", async () => {
        store.set("token", "abc");
        const {initNative} = await import("../src/native/bootstrap.js");
        // the document stub has no addEventListener / querySelector: any listener or DOM change would throw
        await expect(initNative()).resolves.toEqual({lockEnabled: false});
        expect(classes.size).toBe(0);
        expect(store.get("token")).toBe("abc");
        expect(events).toEqual([]);
    });

    it("turns haptics, sharing and the Face ID lock off", async () => {
        const {haptic} = await import("../src/native/haptics.js");
        const {shareText} = await import("../src/native/share.js");
        const {isLockEnabled, biometricInfo, resetLockOnSignOut} = await import("../src/native/biometric.js");

        await expect(haptic("success")).resolves.toBeUndefined();
        await expect(shareText({title: "x", text: "y"})).resolves.toBe(false);
        await expect(isLockEnabled()).resolves.toBe(false);
        await expect(biometricInfo()).resolves.toEqual({available: false, label: "Face ID"});
        expect(resetLockOnSignOut()).toBeUndefined();
        expect(events).toEqual([]); // no "app:lock-setting"
    });

    it("leaves the token in localStorage only", async () => {
        const {restoreToken, saveToken} = await import("../src/native/secureToken.js");
        saveToken("abc");
        await restoreToken();
        expect(store.size).toBe(0);
    });

    it("never times requests out, marks data stale or changes the page", async () => {
        const c = await import("../src/native/connectivity.js");
        expect(c.requestTimeout("/holdings")).toBe(0);
        expect(c.requestTimeout("/analyst?symbol=AAPL")).toBe(0);
        c.setOnline(false);
        c.markStale();
        expect(c.getConnectivity()).toEqual({online: true, stale: false});
        expect(classes.size).toBe(0);
        expect(events).toEqual([]);
        const finished = c.requestStarted();
        finished();
        await expect(c.whenRequestsSettle()).resolves.toBeUndefined();
    });

    it("doesn't fit numbers or watch the page", async () => {
        const {watchNumbers} = await import("../src/native/fitNumbers.js");
        expect(watchNumbers()).toBeUndefined(); // the document stub has no body: observing it would throw
    });

    it("logout clears only the token, with no cache, Keychain or lock work", async () => {
        vi.stubEnv("VITE_BACKEND_URL", "http://api.test");
        store.set("token", "abc");
        store.set("unrelated", "keep");
        const api = await import("../src/services/api.js");
        api.logout();
        expect(store.has("token")).toBe(false);
        expect(store.get("unrelated")).toBe("keep");
        expect(events).toEqual([]);
    });

    it("passes the caller's abort signal to fetch untouched and adds no time limit", async () => {
        vi.stubEnv("VITE_BACKEND_URL", "http://api.test");
        const fetchMock = vi.fn(async () => ({ok: true, status: 200, json: async () => []}));
        vi.stubGlobal("fetch", fetchMock);
        const api = await import("../src/services/api.js");
        await api.getHoldings();
        expect(fetchMock.mock.calls[0][1].signal).toBeUndefined();
        expect(store.size).toBe(0); // nothing cached
    });

    it("leaves text size and outside links to the browser", async () => {
        const {applyPreferredTextSize} = await import("../src/native/textZoom.js");
        const {openLinksInAppBrowser} = await import("../src/native/externalLinks.js");
        await expect(applyPreferredTextSize()).resolves.toBeUndefined();
        // the document stub has no addEventListener: a click listener would throw
        expect(openLinksInAppBrowser()).toBeUndefined();
        expect(events).toEqual([]);
    });

    it("never loads the text size or browser plugins", async () => {
        const loaders = [];
        vi.doMock("../src/native/platform.js", () => ({
            isNative: false,
            loadPlugin: (importer) => {
                const load = vi.fn(importer);
                loaders.push(load);
                return load;
            },
        }));
        const {applyPreferredTextSize} = await import("../src/native/textZoom.js");
        const {openLinksInAppBrowser} = await import("../src/native/externalLinks.js");
        await applyPreferredTextSize();
        openLinksInAppBrowser();
        expect(loaders).toHaveLength(2);
        for (const load of loaders) expect(load).not.toHaveBeenCalled();
    });

    it("keeps the website's tab order (Search first)", async () => {
        const {tabOrder} = await import("../src/native/tabOrder.js");
        const links = [{to: "/search"}, {to: "/dashboard"}, {to: "/transactions"}];
        expect(tabOrder(links)).toBe(links);
        expect(tabOrder(links, false)).toBe(links);
    });
});

describe("text size in the app", () => {
    it("follows the iPhone's setting, capped so layouts still fit", async () => {
        const {textZoomFor, MAX_TEXT_ZOOM, MIN_TEXT_ZOOM} = await import("../src/native/textZoom.js");
        expect(textZoomFor(1)).toBe(1); // the iOS default
        expect(textZoomFor(19 / 17)).toBeCloseTo(1.118); // one step larger
        expect(textZoomFor(3.12)).toBe(MAX_TEXT_ZOOM); // the largest accessibility size
        expect(MAX_TEXT_ZOOM).toBe(1.3);
        expect(textZoomFor(14 / 17)).toBe(MIN_TEXT_ZOOM);
        expect(textZoomFor(undefined)).toBe(1);
        expect(textZoomFor(Number.NaN)).toBe(1);
        expect(textZoomFor(0)).toBe(1);
    });

    it("applies the preferred size through the plugin", async () => {
        const set = vi.fn(async () => undefined);
        vi.doMock("../src/native/platform.js", () => ({
            isNative: true,
            loadPlugin: (importer) => () => (String(importer).includes("text-zoom")
                ? Promise.resolve({TextZoom: {getPreferred: async () => ({value: 2.35}), set}})
                : Promise.reject(new Error("no plugin"))),
        }));
        const {applyPreferredTextSize} = await import("../src/native/textZoom.js");
        await applyPreferredTextSize();
        expect(set).toHaveBeenCalledWith({value: 1.3});
    });

    it("keeps the current size if the plugin fails", async () => {
        inApp();
        const {applyPreferredTextSize} = await import("../src/native/textZoom.js");
        await expect(applyPreferredTextSize()).resolves.toBeUndefined();
    });
});

describe("outside links in the app", () => {
    it("opens only other websites in the in-app browser", async () => {
        const {externalUrl} = await import("../src/native/externalLinks.js");
        const app = "capacitor://localhost";
        expect(externalUrl("https://www.coingecko.com/", app)).toBe("https://www.coingecko.com/");
        expect(externalUrl("http://example.com/a?b=1#c", app)).toBe("http://example.com/a?b=1#c");
        expect(externalUrl("capacitor://localhost/privacy", app)).toBeNull(); // a page of the app
        expect(externalUrl("http://192.168.1.5:5173/privacy", "http://192.168.1.5:5173")).toBeNull(); // live reload
        expect(externalUrl("mailto:someone@example.com", app)).toBeNull(); // Mail, as before
        expect(externalUrl("tel:+15555555555", app)).toBeNull();
        expect(externalUrl("javascript:alert(1)", app)).toBeNull();
        expect(externalUrl("", app)).toBeNull();
        expect(externalUrl(undefined, app)).toBeNull();
    });

    function linkClick(href) {
        const link = {href};
        return {
            target: {closest: (selector) => (selector === "a[href]" ? link : null)},
            defaultPrevented: false,
            preventDefault: vi.fn(),
            stopPropagation: vi.fn(),
        };
    }

    it("catches clicks on outside links before React, and leaves mailto: alone", async () => {
        const open = vi.fn(async () => undefined);
        const listeners = [];
        vi.doMock("../src/native/platform.js", () => ({
            isNative: true,
            loadPlugin: (importer) => () => (String(importer).includes("browser")
                ? Promise.resolve({Browser: {open}})
                : Promise.reject(new Error("no plugin"))),
        }));
        vi.stubGlobal("document", {addEventListener: (type, fn, capture) => listeners.push({type, fn, capture})});
        vi.stubGlobal("window", {location: {origin: "capacitor://localhost"}, open: vi.fn()});
        const {openLinksInAppBrowser} = await import("../src/native/externalLinks.js");
        openLinksInAppBrowser();
        expect(listeners).toHaveLength(1);
        expect(listeners[0]).toMatchObject({type: "click", capture: true});

        const outside = linkClick("https://www.exchangerate-api.com/");
        listeners[0].fn(outside);
        expect(outside.preventDefault).toHaveBeenCalled();
        await vi.waitFor(() => expect(open).toHaveBeenCalledWith(expect.objectContaining({url: "https://www.exchangerate-api.com/"})));

        const mail = linkClick("mailto:someone@example.com");
        listeners[0].fn(mail);
        const inside = linkClick("capacitor://localhost/dashboard");
        listeners[0].fn(inside);
        expect(mail.preventDefault).not.toHaveBeenCalled();
        expect(inside.preventDefault).not.toHaveBeenCalled();
        expect(open).toHaveBeenCalledTimes(1);
    });
});

describe("tab bar in the app", () => {
    it("starts with Dashboard, the screen the app opens on", async () => {
        const {tabOrder} = await import("../src/native/tabOrder.js");
        const links = ["/search", "/dashboard", "/transactions", "/holdings", "/user"].map((to) => ({to}));
        expect(tabOrder(links, true).map((link) => link.to))
            .toEqual(["/dashboard", "/search", "/transactions", "/holdings", "/user"]);
    });
});

describe("loadPlugin", () => {
    it("imports a plugin once and reuses it", async () => {
        const {loadPlugin} = await import("../src/native/platform.js");
        const importer = vi.fn(async () => ({ok: true}));
        const load = loadPlugin(importer);
        await load();
        await load();
        expect(importer).toHaveBeenCalledTimes(1);
    });
});

describe("Face ID lock rules", () => {
    const base = {enabled: true, signedIn: true, promptOpen: false, settling: false};

    it("covers the app when it's left, remembering whether it was unlocked", async () => {
        const {onLeave} = await import("../src/native/lockRules.js");
        expect(onLeave({...base, locked: false})).toEqual({cover: true, unlockedWhenLeft: true});
        expect(onLeave({...base, locked: true})).toEqual({cover: true, unlockedWhenLeft: false});
        expect(onLeave({...base, promptOpen: true, locked: false})).toEqual({cover: false}); // the Face ID sheet
        // leaving right after unlocking (the sheet is still settling) must still cover the app
        expect(onLeave({...base, settling: true, locked: false})).toEqual({cover: true, unlockedWhenLeft: true});
        expect(onLeave({...base, enabled: false, locked: false})).toEqual({cover: false});
        expect(onLeave({...base, signedIn: false, locked: false})).toEqual({cover: false});
    });

    it("covers an app that really leaves while the Face ID sheet is open", async () => {
        const {onLeave} = await import("../src/native/lockRules.js");
        // Account -> Security toggle -> Face ID sheet -> home swipe: only the background event tells them apart
        expect(onLeave({...base, promptOpen: true, backgrounded: true, locked: false}))
            .toEqual({cover: true, unlockedWhenLeft: true});
        expect(onLeave({...base, promptOpen: true, backgrounded: true, enabled: false, locked: false}))
            .toEqual({cover: false});
    });

    it("only skips Face ID for a quick return to an app that was unlocked", async () => {
        const {onReturn, GRACE_MS} = await import("../src/native/lockRules.js");
        expect(onReturn({...base, locked: true, unlockedWhenLeft: true, away: 5000})).toBe("unlock");
        expect(onReturn({...base, locked: true, unlockedWhenLeft: true, away: GRACE_MS + 1})).toBe("ask");
        expect(onReturn({...base, locked: true, unlockedWhenLeft: true, away: undefined})).toBe("ask");
    });

    it("never unlocks an app that was already locked (cancel Face ID, then flick Control Center)", async () => {
        const {onReturn} = await import("../src/native/lockRules.js");
        expect(onReturn({...base, locked: true, unlockedWhenLeft: false, away: 200})).toBe("ask");
    });

    it("ignores returns while the Face ID sheet is closing, when off, or when signed out", async () => {
        const {onReturn} = await import("../src/native/lockRules.js");
        const quick = {locked: true, unlockedWhenLeft: true, away: 200};
        expect(onReturn({...base, ...quick, settling: true})).toBe("ignore");
        expect(onReturn({...base, ...quick, enabled: false})).toBe("ignore");
        expect(onReturn({...base, ...quick, signedIn: false})).toBe("ignore");
        expect(onReturn({...base, ...quick, locked: false})).toBe("ignore");
    });

    it("starts covered after a slow start, even before the login is restored", async () => {
        const {initiallyLocked} = await import("../src/native/lockRules.js");
        expect(initiallyLocked({enabled: null, signedIn: false})).toBe(true); // Keychain not answered yet
        expect(initiallyLocked({enabled: null, signedIn: true})).toBe(true);
        expect(initiallyLocked({enabled: true, signedIn: true})).toBe(true);
        expect(initiallyLocked({enabled: true, signedIn: false})).toBe(false);
        expect(initiallyLocked({enabled: false, signedIn: true})).toBe(false);
    });

    it("after a slow start, opens only when signed out or the lock is known to be off", async () => {
        const {onStartup} = await import("../src/native/lockRules.js");
        expect(onStartup({enabled: true, signedIn: true})).toBe("ask");
        expect(onStartup({enabled: null, signedIn: true})).toBe("ask"); // still unreadable: fail closed
        expect(onStartup({enabled: false, signedIn: true})).toBe("open");
        expect(onStartup({enabled: true, signedIn: false})).toBe("open");
        expect(onStartup({enabled: null, signedIn: false})).toBe("open");
    });

    it("calls it Passcode when no face or finger is enrolled", async () => {
        const {biometryLabel} = await import("../src/native/lockRules.js");
        expect(biometryLabel({isAvailable: true, strongBiometryIsAvailable: true, biometryType: 2})).toBe("Face ID");
        expect(biometryLabel({isAvailable: true, strongBiometryIsAvailable: true, biometryType: 1})).toBe("Touch ID");
        // Face ID hardware, no face set up: iOS still reports FACE_ID, but only the passcode will be asked for
        expect(biometryLabel({isAvailable: true, strongBiometryIsAvailable: false, biometryType: 2})).toBe("Passcode");
        expect(biometryLabel({isAvailable: false, strongBiometryIsAvailable: false, biometryType: 0})).toBe("Face ID");
        expect(biometryLabel()).toBe("Face ID");
    });

    it("words the Account page naturally for Face ID, Touch ID and the passcode", async () => {
        const {lockWording} = await import("../src/native/lockRules.js");
        const face = lockWording("Face ID");
        expect(face.title).toBe("Require Face ID");
        expect(face.turnedOn).toBe("Face ID lock turned on");
        expect(face.hint).toContain("Face ID");
        expect(lockWording("Touch ID").turnedOff).toBe("Touch ID lock turned off");

        const passcode = lockWording("Passcode");
        const all = Object.values(passcode).join(" ");
        expect(all).not.toMatch(/Passcode or your passcode|Passcode lock|with Passcode/);
        expect(passcode.hint).toBe("Lock Zenith whenever you leave the app. Open it again with your iPhone passcode.");
        expect(passcode.turnedOn).toBe("Zenith will now ask for your passcode");
        expect(lockWording()).toEqual(face);
    });
});

describe("Face ID lock in the app", () => {
    it("is turned off by every sign out", async () => {
        const set = vi.fn();
        const remove = vi.fn(async () => undefined);
        vi.doMock("../src/native/platform.js", () => ({
            isNative: true,
            loadPlugin: (importer) => () => (String(importer).includes("preferences")
                ? Promise.resolve({Preferences: {set, remove}})
                : Promise.reject(new Error("no plugin"))),
        }));
        vi.stubEnv("VITE_BACKEND_URL", "http://api.test");
        store.set("token", "abc");
        const api = await import("../src/services/api.js");
        api.logout();
        await vi.waitFor(() => expect(events).toContain("app:lock-setting"));
        expect(remove).toHaveBeenCalledWith({key: "biometricLock"});
        expect(set).not.toHaveBeenCalled();
        expect(store.has("token")).toBe(false);
    });
});

describe("pull to refresh rules", () => {
    it("only works on the pages that reload", async () => {
        const {canPullToRefresh} = await import("../src/native/refreshRules.js");
        expect(canPullToRefresh("/dashboard")).toBe(true);
        expect(canPullToRefresh("/holdings/")).toBe(true);
        expect(canPullToRefresh("/transactions")).toBe(true);
        expect(canPullToRefresh("/search")).toBe(false);
        expect(canPullToRefresh("/user")).toBe(false);
    });

    it("says it's offline instead of pretending to refresh", async () => {
        const {pullAction} = await import("../src/native/refreshRules.js");
        expect(pullAction({online: true, stale: false})).toBe("refresh");
        expect(pullAction({online: true, stale: true})).toBe("refresh"); // the server may be back
        expect(pullAction({online: false, stale: false})).toBe("offline");
    });
});

describe("haptics only on a real change", () => {
    const element = (attrs = {}, classNames = []) => ({
        getAttribute: (name) => attrs[name] ?? null,
        classList: {contains: (c) => classNames.includes(c)},
        disabled: attrs.disabled === true,
    });

    it("skips the current tab and the selected option", async () => {
        const {isAlreadySelected} = await import("../src/native/bootstrap.js");
        expect(isAlreadySelected(element({"aria-current": "page"}))).toBe(true);
        expect(isAlreadySelected(element({"aria-pressed": "true"}))).toBe(true);
        expect(isAlreadySelected(element({}, ["active"]))).toBe(true);
        expect(isAlreadySelected(element())).toBe(false);
        expect(isAlreadySelected(element({"aria-pressed": "false"}))).toBe(false);
    });
});

describe("fitting big numbers", () => {
    it("shrinks only what overflows, never below 60%", async () => {
        const {fittedSize} = await import("../src/native/fitNumbers.js");
        expect(fittedSize({baseSize: 24, naturalWidth: 100, availableWidth: 150})).toBeNull();
        expect(fittedSize({baseSize: 24, naturalWidth: 200, availableWidth: 150})).toBe(18);
        expect(fittedSize({baseSize: 24, naturalWidth: 1000, availableWidth: 150})).toBeCloseTo(14.4);
        expect(fittedSize({baseSize: 24, naturalWidth: 200, availableWidth: 0})).toBeNull(); // not laid out
    });
});

describe("offline cache", () => {
    const user = (currency = "CAD", id = "u1") => ({id, name: "Ana", currency});

    it("is off on the website", async () => {
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/user", user());
        remember("/holdings", [{symbol: "AAPL"}]);
        expect(recall("/holdings")).toBeUndefined();
        expect(store.size).toBe(0);
    });

    it("in the app keeps portfolio screens, skips the rest and is cleared on sign out", async () => {
        inApp();
        const {remember, recall, forgetAll} = await import("../src/native/offlineCache.js");
        remember("/user", user());
        remember("/holdings", [{symbol: "AAPL"}]);
        remember("/transactions?symbol=AAPL", [{id: 1}]);
        remember("/assets/search/stock?asset=A", [{symbol: "A"}]); // not a portfolio screen
        store.set("token", "abc");

        expect(recall("/user")).toEqual(user());
        expect(recall("/holdings")).toEqual([{symbol: "AAPL"}]);
        expect(recall("/transactions?symbol=AAPL")).toEqual([{id: 1}]);
        expect(recall("/assets/search/stock?asset=A")).toBeUndefined();

        forgetAll();
        expect(recall("/holdings")).toBeUndefined();
        expect(recall("/user")).toBeUndefined();
        expect([...store.keys()]).toEqual(["token"]); // only the cache is removed
    });

    it("saves nothing until it knows whose data it is", async () => {
        inApp();
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/holdings", [{symbol: "AAPL"}]);
        remember("/user", user());
        expect(recall("/holdings")).toBeUndefined();
    });

    it("keeps each currency apart, so a currency change never shows the old amounts", async () => {
        inApp();
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/user", user("CAD"));
        remember("/holdings", [{value: 100}]);
        remember("/user/information", user("EUR"), {get: false}); // the reply to saving the new currency
        expect(recall("/holdings")).toBeUndefined();
        remember("/holdings", [{value: 68}]);
        expect(recall("/holdings")).toEqual([{value: 68}]);
        remember("/user/information", user("CAD"), {get: false});
        expect(recall("/holdings")).toEqual([{value: 100}]);
    });

    it("keeps each account apart", async () => {
        inApp();
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/user", user("CAD", "u1"));
        remember("/holdings", [{symbol: "AAPL"}]);
        remember("/user", user("CAD", "u2"));
        expect(recall("/holdings")).toBeUndefined();
    });

    it("drops replies that started before a sign out or a currency change", async () => {
        inApp();
        const {cacheTicket, remember, recall, forgetAll} = await import("../src/native/offlineCache.js");
        remember("/user", user("CAD"));
        const beforeSignOut = cacheTicket();
        forgetAll();
        remember("/user", user("CAD", "previous"), {ticket: beforeSignOut});
        remember("/holdings", [{symbol: "OLD"}], {ticket: beforeSignOut});
        expect(store.size).toBe(0);

        remember("/user", user("CAD"));
        const inCad = cacheTicket();
        remember("/user/information", user("EUR"), {get: false});
        remember("/dashboard?current_timeperiod=1d", {value: 100}, {ticket: inCad}); // CAD amounts, now EUR
        expect(recall("/dashboard?current_timeperiod=1d")).toBeUndefined();
    });

    it("keeps at most 40 entries, evicting the least recently used", async () => {
        inApp();
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/user", user());
        remember("/holdings", [{symbol: "KEEP"}]);
        for (let i = 0; i < 60; i++) {
            remember(`/dashboard?current_timeperiod=${i}`, {i});
            if (i % 10 === 0) recall("/holdings"); // in use, so it stays
        }
        const entries = [...store.keys()].filter((k) => k.startsWith("offline:"));
        expect(entries.length).toBeLessThanOrEqual(40);
        expect(recall("/holdings")).toEqual([{symbol: "KEEP"}]);
        expect(recall("/dashboard?current_timeperiod=59")).toEqual({i: 59});
        expect(recall("/dashboard?current_timeperiod=0")).toBeUndefined();
    });

    it("keeps only the latest few chart and filter variants", async () => {
        inApp();
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/user", user());
        for (let i = 0; i < 20; i++) remember(`/prices/history?symbol=S${i}&type=stock&range=1y`, {i});
        const charts = [...store.keys()].filter((k) => k.includes("/prices/history"));
        expect(charts).toHaveLength(8);
        expect(recall("/prices/history?symbol=S19&type=stock&range=1y")).toEqual({i: 19});
        expect(recall("/prices/history?symbol=S0&type=stock&range=1y")).toBeUndefined();
        expect(recall("/user")).toEqual(user()); // other screens aren't touched by the chart limit
    });
});

describe("requests in the app", () => {
    let fetchMock;
    let api;

    // a fetch that never answers, like a dead connection, and only ends when aborted
    const hang = (url, {signal}) => new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
    });
    const reply = (body) => async () => ({ok: true, status: 200, json: async () => body});

    beforeEach(async () => {
        inApp();
        vi.stubEnv("VITE_BACKEND_URL", "http://api.test");
        fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        api = await import("../src/services/api.js");
    });

    async function cacheHoldings() {
        fetchMock.mockImplementationOnce(reply({id: "u1", name: "Ana", currency: "CAD"}));
        await api.getUser();
        fetchMock.mockImplementationOnce(reply([{symbol: "AAPL"}]));
        await api.getHoldings();
    }

    it("give up after 12 s and show the saved copy, marked stale", async () => {
        await cacheHoldings();
        vi.useFakeTimers();
        fetchMock.mockImplementation(hang);
        const result = api.getHoldings();
        await vi.advanceTimersByTimeAsync(12000);
        await expect(result).resolves.toEqual([{symbol: "AAPL"}]);
        expect(events).toContain("app:stale");
        expect(classes.has("offline")).toBe(true); // moves the page below the banner

        // the next answer from the server clears it
        vi.useRealTimers();
        fetchMock.mockImplementation(reply([{symbol: "AAPL"}, {symbol: "MSFT"}]));
        await api.getHoldings();
        expect(classes.has("offline")).toBe(false);
    });

    it("say the server is too slow when nothing is saved", async () => {
        vi.useFakeTimers();
        fetchMock.mockImplementation(hang);
        const result = api.getHoldings();
        const check = expect(result).rejects.toThrow("taking too long");
        await vi.advanceTimersByTimeAsync(12000);
        await check;
    });

    it("show the saved copy when the connection fails outright", async () => {
        await cacheHoldings();
        fetchMock.mockRejectedValue(new TypeError("Load failed"));
        await expect(api.getHoldings()).resolves.toEqual([{symbol: "AAPL"}]);
        expect(events).toContain("app:stale");
    });

    it("still let the caller cancel, without falling back to saved data", async () => {
        fetchMock.mockImplementation(hang);
        const controller = new AbortController();
        const result = api.getAnalystReport({symbol: "AAPL", type: "stock"}, {signal: controller.signal});
        controller.abort();
        await expect(result).rejects.toMatchObject({name: "AbortError"});
        expect(events).not.toContain("app:stale");
    });

    it("give the market analyst longer than other requests", async () => {
        const {requestTimeout} = await import("../src/native/connectivity.js");
        expect(requestTimeout("/holdings")).toBe(12000);
        expect(requestTimeout("/analyst?symbol=AAPL&type=stock")).toBeGreaterThan(12000);
    });

    it("don't save a reply that arrives after signing out", async () => {
        await cacheHoldings();
        let answer;
        fetchMock.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
        const pending = api.getDashboardStats("1d");
        api.logout();
        answer({ok: true, status: 200, json: async () => ({value: 1})});
        await pending;
        expect([...store.keys()].filter((k) => k.startsWith("offline"))).toEqual([]);
    });
});
