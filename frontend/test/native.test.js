import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

// The native helpers must be complete no-ops on the website: no plugin calls, no state, no changes to the page.

let store;
let classes;

beforeEach(() => {
    vi.resetModules();
    store = new Map();
    classes = new Set();
    vi.stubGlobal("localStorage", {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
        removeItem: (k) => store.delete(k),
    });
    vi.stubGlobal("document", {documentElement: {classList: {add: (c) => classes.add(c)}}});
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("native helpers on the website", () => {
    it("knows it isn't running in the app", async () => {
        const {isNative} = await import("../src/native/platform.js");
        expect(isNative).toBe(false);
    });

    it("starts without touching the page or the token", async () => {
        store.set("token", "abc");
        const {initNative} = await import("../src/native/bootstrap.js");
        await expect(initNative()).resolves.toEqual({lockEnabled: false});
        expect(classes.size).toBe(0);
        expect(store.get("token")).toBe("abc");
    });

    it("turns haptics, sharing and the Face ID lock off", async () => {
        const {haptic} = await import("../src/native/haptics.js");
        const {shareText} = await import("../src/native/share.js");
        const {isLockEnabled, biometricInfo} = await import("../src/native/biometric.js");

        await expect(haptic("success")).resolves.toBeUndefined();
        await expect(shareText({title: "x", text: "y"})).resolves.toBe(false);
        await expect(isLockEnabled()).resolves.toBe(false);
        await expect(biometricInfo()).resolves.toEqual({available: false, label: "Face ID"});
    });

    it("leaves the token in localStorage only", async () => {
        const {restoreToken, saveToken} = await import("../src/native/secureToken.js");
        saveToken("abc");
        await restoreToken();
        expect(store.size).toBe(0);
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
});

describe("offline cache", () => {
    it("is off on the website", async () => {
        const {remember, recall} = await import("../src/native/offlineCache.js");
        remember("/holdings", [{symbol: "AAPL"}]);
        expect(recall("/holdings")).toBeUndefined();
        expect(store.size).toBe(0);
    });

    it("in the app keeps portfolio screens, skips the rest and is cleared on sign out", async () => {
        vi.doMock("../src/native/platform.js", () => ({isNative: true, loadPlugin: () => () => Promise.reject()}));
        // like the real localStorage, Object.keys() lists the stored keys
        vi.stubGlobal("localStorage", new Proxy(localStorage, {
            ownKeys: () => [...store.keys()],
            getOwnPropertyDescriptor: () => ({enumerable: true, configurable: true}),
        }));

        const {remember, recall, forgetAll} = await import("../src/native/offlineCache.js");
        remember("/holdings", [{symbol: "AAPL"}]);
        remember("/transactions?symbol=AAPL", [{id: 1}]);
        remember("/assets/search/stock?asset=A", [{symbol: "A"}]); // not a portfolio screen
        store.set("token", "abc");

        expect(recall("/holdings")).toEqual([{symbol: "AAPL"}]);
        expect(recall("/transactions?symbol=AAPL")).toEqual([{id: 1}]);
        expect(recall("/assets/search/stock?asset=A")).toBeUndefined();

        forgetAll();
        expect(recall("/holdings")).toBeUndefined();
        expect(store.get("token")).toBe("abc"); // only the cached screens are removed
        vi.doUnmock("../src/native/platform.js");
    });
});
