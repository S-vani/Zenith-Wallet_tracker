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
