import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

// App Store launch helpers: links back into the app (zenithwallet://), the app version header and the forced update
// (426) screen. Like native.test.js, the app-only parts are tested with platform.js mocked to say "native".

let store;
let classes;
let events;

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

// the app, with @capacitor/app answering getInfo() with this version (null: the plugin fails)
function inApp(version = "1.2.0") {
    const plugin = version === null
        ? Promise.reject(new Error("no plugin"))
        : Promise.resolve({App: {getInfo: async () => ({version, build: "7"})}});
    plugin.catch(() => null); // only rejected on purpose
    vi.doMock("../src/native/platform.js", () => ({isNative: true, loadPlugin: () => () => plugin}));
}

const reply = (status, body) => async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
});

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
    vi.stubGlobal("window", {dispatchEvent: (e) => events.push(e)});
    vi.stubEnv("VITE_BACKEND_URL", "http://api.test");
});

afterEach(() => {
    vi.doUnmock("../src/native/platform.js");
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

const eventTypes = () => events.map((e) => e.type);

describe("Open the Zenith app button", () => {
    it("is offered on iPhone, iPod and iPad browsers only", async () => {
        const {isAppleMobileBrowser} = await import("../src/utils/appLink.js");
        const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1";
        const ipadOld = "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";
        const ipadDesktop = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15";
        const android = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36";

        expect(isAppleMobileBrowser({userAgent: iphone, maxTouchPoints: 5})).toBe(true);
        expect(isAppleMobileBrowser({userAgent: ipadOld, maxTouchPoints: 5})).toBe(true);
        // iPadOS asks for the desktop site: a "Mac" with a touch screen
        expect(isAppleMobileBrowser({userAgent: ipadDesktop, maxTouchPoints: 5})).toBe(true);
        expect(isAppleMobileBrowser({userAgent: ipadDesktop, maxTouchPoints: 0})).toBe(false); // a real Mac
        expect(isAppleMobileBrowser({userAgent: android, maxTouchPoints: 5})).toBe(false);
        expect(isAppleMobileBrowser()).toBe(false);
    });

    it("links to the log in screen with nothing else in the URL", async () => {
        const {APP_LOGIN_URL} = await import("../src/utils/appLink.js");
        expect(APP_LOGIN_URL).toBe("zenithwallet://login");
    });
});

describe("zenithwallet:// links in the app", () => {
    it("open only known screens", async () => {
        const {appLinkPath} = await import("../src/native/appLinks.js");
        expect(appLinkPath("zenithwallet://login")).toBe("/login");
        expect(appLinkPath("zenithwallet://login/")).toBe("/login");
        expect(appLinkPath("ZenithWallet://LOGIN")).toBe("/login");
        expect(appLinkPath("zenithwallet:///login")).toBe("/login");
        expect(appLinkPath("zenithwallet://login?token=abc")).toBe("/login"); // extra data is ignored, never used

        expect(appLinkPath("zenithwallet://dashboard")).toBeNull();
        expect(appLinkPath("zenithwallet://user")).toBeNull();
        expect(appLinkPath("zenithwallet://constructor")).toBeNull();
        expect(appLinkPath("https://zenithwalletracker.ca/login")).toBeNull();
        expect(appLinkPath("otherapp://login")).toBeNull();
        expect(appLinkPath("not a url")).toBeNull();
        expect(appLinkPath(undefined)).toBeNull();
    });

    it("do nothing on the website", async () => {
        const {handleAppUrl, takePendingAppLink} = await import("../src/native/appLinks.js");
        handleAppUrl("zenithwallet://login");
        expect(takePendingAppLink()).toBeNull();
        expect(events).toEqual([]);
    });

    it("are kept for the router and announced", async () => {
        inApp();
        const {handleAppUrl, takePendingAppLink} = await import("../src/native/appLinks.js");
        handleAppUrl("zenithwallet://somewhere-else");
        expect(events).toEqual([]);

        handleAppUrl("zenithwallet://login");
        expect(eventTypes()).toEqual(["app:navigate"]);
        expect(events[0].detail).toEqual({path: "/login"});
        expect(takePendingAppLink()).toBe("/login");
        expect(takePendingAppLink()).toBeNull(); // read once
    });
});

describe("app version", () => {
    it("accepts only plain version strings", async () => {
        const {cleanVersion} = await import("../src/native/appVersion.js");
        expect(cleanVersion("1.2.0")).toBe("1.2.0");
        expect(cleanVersion(" 1.2 ")).toBe("1.2");
        expect(cleanVersion("2.0.0-beta.1")).toBe("2.0.0-beta.1");
        expect(cleanVersion("")).toBeNull();
        expect(cleanVersion("1.0\r\nX-Evil: 1")).toBeNull();
        expect(cleanVersion("x".repeat(40))).toBeNull();
        expect(cleanVersion(undefined)).toBeNull();
        expect(cleanVersion(12)).toBeNull();
    });

    it("is never sent from the website", async () => {
        const {appVersionHeaders, loadAppVersion} = await import("../src/native/appVersion.js");
        await expect(loadAppVersion()).resolves.toBeNull();
        expect(appVersionHeaders()).toEqual({});
    });

    it("is read once in the app and then sent with every request", async () => {
        inApp("1.4.2");
        const {appVersionHeaders, loadAppVersion} = await import("../src/native/appVersion.js");
        expect(appVersionHeaders()).toEqual({}); // not known yet: requests aren't held up
        await loadAppVersion();
        expect(appVersionHeaders()).toEqual({"X-Zenith-App-Version": "1.4.2"});

        const fetchMock = vi.fn(reply(200, {status: "ok"}));
        vi.stubGlobal("fetch", fetchMock);
        const api = await import("../src/services/api.js");
        await api.getAuthProviders();
        expect(fetchMock.mock.calls[0][1].headers["X-Zenith-App-Version"]).toBe("1.4.2");

        fetchMock.mockImplementation(reply(200, {access_token: "t"}));
        await api.loginAuthentication({email: "a@b.co", password: "pw"});
        expect(fetchMock.mock.calls[1][1].headers["X-Zenith-App-Version"]).toBe("1.4.2");
    });

    it("is left out when the plugin fails", async () => {
        inApp(null);
        const {appVersionHeaders, loadAppVersion} = await import("../src/native/appVersion.js");
        await expect(loadAppVersion()).resolves.toBeNull();
        expect(appVersionHeaders()).toEqual({});
    });
});

describe("update required (426)", () => {
    const UPDATE = {detail: "Please update Zenith from the App Store.", code: "UPDATE_REQUIRED"};

    it("reads the server's message, with a fallback", async () => {
        const {updateMessageFrom, DEFAULT_UPDATE_MESSAGE} = await import("../src/native/updateRequired.js");
        expect(updateMessageFrom(UPDATE)).toBe("Please update Zenith from the App Store.");
        expect(updateMessageFrom({detail: {message: "Update please"}})).toBe("Update please");
        expect(updateMessageFrom({detail: "  "})).toBe(DEFAULT_UPDATE_MESSAGE);
        expect(updateMessageFrom(null)).toBe(DEFAULT_UPDATE_MESSAGE);
    });

    it("opens App Store addresses in the App Store app, and hides the button otherwise", async () => {
        const {appStoreLink} = await import("../src/native/updateRequired.js");
        expect(appStoreLink("https://apps.apple.com/app/id1234567890")).toBe("itms-apps://apps.apple.com/app/id1234567890");
        expect(appStoreLink("https://apps.apple.com/ca/app/zenith/id123?mt=8")).toBe("itms-apps://apps.apple.com/ca/app/zenith/id123?mt=8");
        expect(appStoreLink("itms-apps://apps.apple.com/app/id1")).toBe("itms-apps://apps.apple.com/app/id1");
        expect(appStoreLink("")).toBeNull();
        expect(appStoreLink(undefined)).toBeNull();
        expect(appStoreLink("http://apps.apple.com/app/id1")).toBeNull();
        expect(appStoreLink("https://apps.apple.com.evil.test/app/id1")).toBeNull();
        expect(appStoreLink("javascript:alert(1)")).toBeNull();
    });

    it("on the website is an ordinary error with no screen", async () => {
        store.set("token", "abc");
        vi.stubGlobal("fetch", vi.fn(reply(426, UPDATE)));
        const api = await import("../src/services/api.js");
        const {getUpdateRequired} = await import("../src/native/updateRequired.js");
        await expect(api.getHoldings()).rejects.toMatchObject({status: 426, code: "UPDATE_REQUIRED"});
        expect(getUpdateRequired()).toBeNull();
        expect(classes.size).toBe(0);
        expect(store.get("token")).toBe("abc");
    });

    it("in the app shows the update screen, keeps the login and never falls back to saved data", async () => {
        inApp();
        store.set("token", "abc");
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        const api = await import("../src/services/api.js");
        const {getUpdateRequired, subscribeUpdateRequired} = await import("../src/native/updateRequired.js");
        const listener = vi.fn();
        subscribeUpdateRequired(listener);

        // a saved copy exists, as after any earlier visit
        fetchMock.mockImplementationOnce(reply(200, {id: "u1", name: "Ana", currency: "CAD"}));
        await api.getUser();
        fetchMock.mockImplementationOnce(reply(200, [{symbol: "AAPL"}]));
        await api.getHoldings();
        const saved = [...store.keys()].filter((k) => k.startsWith("offline")).sort();

        fetchMock.mockImplementation(reply(426, UPDATE));
        await expect(api.getHoldings()).rejects.toMatchObject({
            status: 426, code: "UPDATE_REQUIRED", message: UPDATE.detail,
        });
        expect(getUpdateRequired()).toBe(UPDATE.detail);
        expect(listener).toHaveBeenCalledTimes(1);
        expect(classes.has("update-required")).toBe(true);

        expect(store.get("token")).toBe("abc"); // not signed out
        expect(eventTypes()).not.toContain("auth:expired");
        expect(eventTypes()).not.toContain("app:stale");
        expect([...store.keys()].filter((k) => k.startsWith("offline")).sort()).toEqual(saved); // nothing new cached

        // the log in form shows it too
        await expect(api.loginAuthentication({email: "a@b.co", password: "pw"}))
            .rejects.toMatchObject({status: 426});
        expect(listener).toHaveBeenCalledTimes(1); // same message, no extra update
    });

    it("in the app copes with a 426 without a readable body", async () => {
        inApp();
        vi.stubGlobal("fetch", vi.fn(async () => ({
            ok: false,
            status: 426,
            json: async () => {
                throw new SyntaxError("Unexpected end of JSON input");
            },
        })));
        const api = await import("../src/services/api.js");
        const {getUpdateRequired, DEFAULT_UPDATE_MESSAGE} = await import("../src/native/updateRequired.js");
        await expect(api.getAuthProviders()).rejects.toMatchObject({status: 426});
        expect(getUpdateRequired()).toBe(DEFAULT_UPDATE_MESSAGE);
    });
});
