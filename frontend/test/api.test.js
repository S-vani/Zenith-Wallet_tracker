import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

// api.js reads the backend url at import time, so set it first and import the module fresh for each test
const BASE = "http://api.test";
let api;
let fetchMock;
let store;
let events;

function respond(status, body) {
    return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => {
            if (body instanceof Error) throw body;
            return body;
        },
    };
}

beforeEach(async () => {
    vi.resetModules();
    vi.stubEnv("VITE_BACKEND_URL", BASE);

    store = new Map();
    events = [];
    vi.stubGlobal("localStorage", {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
        removeItem: (k) => store.delete(k),
    });
    vi.stubGlobal("window", {dispatchEvent: (e) => events.push(e.type)});
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    api = await import("../src/services/api.js");
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

describe("error messages", () => {
    it.each([
        ["LOGIN_BAD_CREDENTIALS", "Incorrect email or password."],
        ["LOGIN_USER_NOT_VERIFIED", "Please verify your email before logging in."],
    ])("maps %s on login", async (code, message) => {
        fetchMock.mockResolvedValue(respond(400, {detail: code}));
        await expect(api.loginAuthentication({email: "a@b.co", password: "x"})).rejects.toThrow(message);
    });

    it("maps fastapi-users error objects", async () => {
        fetchMock.mockResolvedValue(respond(400, {detail: {code: "REGISTER_INVALID_PASSWORD", reason: "short"}}));
        await expect(api.signupAuthentication({email: "a@b.co", password: "x", name: "A", currency: "CAD"}))
            .rejects.toThrow("That password isn't allowed. Try a longer one.");
    });

    it("uses the reason of unknown error codes", async () => {
        fetchMock.mockResolvedValue(respond(400, {detail: {code: "SOMETHING_NEW", reason: "Because."}}));
        await expect(api.verify("t")).rejects.toThrow("Because.");
    });

    it("passes plain string details through", async () => {
        fetchMock.mockResolvedValue(respond(409, {detail: "Insufficient holdings"}));
        await expect(api.createTransaction({})).rejects.toThrow("Insufficient holdings");
    });

    it.each([
        [{loc: ["body", "quantity"], msg: "Input should be less than or equal to 1000000000000", ctx: {le: 1e12}},
            "Quantity is too large."],
        [{loc: ["body", "price_of_one"], msg: "Input should be greater than 0", ctx: {gt: 0}},
            "Price must be greater than 0."],
        [{loc: ["body", "name"], msg: "String should have at least 1 character", ctx: {min_length: 1}},
            "Name can't be empty."],
        [{loc: ["body", "name"], msg: "String should have at most 100 characters", ctx: {max_length: 100}},
            "Name must be 100 characters or fewer."],
        [{loc: ["body", "email"], msg: "value is not a valid email address"}, "Please enter a valid email address."],
        [{loc: ["body", "asset_type"], msg: "Input should be 'stock' or 'crypto'"},
            "Asset type: Input should be 'stock' or 'crypto'"],
        [{loc: ["body", "mystery"], msg: "Value error, nope"}, "This field: nope"],
    ])("turns validation errors into readable text (%#)", async (detail, message) => {
        fetchMock.mockResolvedValue(respond(422, {detail: [detail]}));
        await expect(api.putUserInfo({})).rejects.toThrow(message);
    });

    it("falls back when the body isn't json", async () => {
        fetchMock.mockResolvedValue(respond(500, new SyntaxError("not json")));
        await expect(api.getHoldings()).rejects.toThrow("Failed to load your holdings.");
    });

    it("reports network failures", async () => {
        fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
        await expect(api.getUser()).rejects.toThrow("Can't reach the server.");
    });

    it("signs the user out when the session expired", async () => {
        store.set("token", "old");
        fetchMock.mockResolvedValue(respond(401, {detail: "Unauthorized"}));

        await expect(api.getUser()).rejects.toThrow("Your session has expired.");
        expect(store.has("token")).toBe(false);
        expect(events).toEqual(["auth:expired"]);
    });

    it("does not sign out on 401 for public requests", async () => {
        store.set("token", "keep");
        fetchMock.mockResolvedValue(respond(401, {detail: "nope"}));
        await expect(api.getUserCount()).rejects.toThrow("nope");
        expect(store.get("token")).toBe("keep");
    });
});

describe("requests", () => {
    it("stores the token after logging in and sends it afterwards", async () => {
        fetchMock.mockResolvedValueOnce(respond(200, {access_token: "abc", token_type: "bearer"}));
        await api.loginAuthentication({email: "  me@example.com ", password: "pw"});

        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/auth/jwt/login`);
        expect(init.body.get("username")).toBe("me@example.com");
        expect(store.get("token")).toBe("abc");

        fetchMock.mockResolvedValueOnce(respond(200, {name: "Me"}));
        await api.getUser();
        expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer abc");
    });

    it("builds transaction filters with local day boundaries", async () => {
        fetchMock.mockResolvedValue(respond(200, []));
        await api.getTransactions({symbol: " aapl ", action: "SELL", start_date: "2024-06-03", end_date: "2024-06-04"});

        const url = new URL(fetchMock.mock.calls[0][0]);
        expect(url.searchParams.get("symbol")).toBe("aapl");
        expect(url.searchParams.get("action")).toBe("SELL");
        expect(url.searchParams.get("start_date")).toBe(new Date("2024-06-03T00:00:00").toISOString());
        expect(url.searchParams.get("end_date")).toBe(new Date("2024-06-04T23:59:59.999").toISOString());
    });

    it("leaves out empty filters", async () => {
        fetchMock.mockResolvedValue(respond(200, []));
        await api.getTransactions({});
        expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/transactions?`);
    });

    it("trims signup fields", async () => {
        fetchMock.mockResolvedValue(respond(201, {}));
        await api.signupAuthentication({email: " a@b.co ", password: " pw ", name: "  Ann ", currency: "USD"});
        expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(
            {email: "a@b.co", password: " pw ", name: "Ann", currency: "USD"});
    });

    it("encodes search queries", async () => {
        fetchMock.mockResolvedValue(respond(200, []));
        await api.searchStock("A&B");
        expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/assets/search/stock?asset=A%26B`);
    });
});

describe("getAnalystReport", () => {
    it("sends symbol, type and the optional coin id / refresh flag", async () => {
        fetchMock.mockResolvedValue(respond(200, {status: "ok"}));

        await api.getAnalystReport({symbol: "BTC-USD", type: "crypto", coinId: "bitcoin", refresh: true});
        let url = new URL(fetchMock.mock.calls[0][0]);
        expect(url.pathname).toBe("/analyst");
        expect(Object.fromEntries(url.searchParams)).toEqual(
            {symbol: "BTC-USD", type: "crypto", coin_id: "bitcoin", refresh: "true"});

        await api.getAnalystReport({symbol: "AAPL", type: "stock"});
        url = new URL(fetchMock.mock.calls[1][0]);
        expect(Object.fromEntries(url.searchParams)).toEqual({symbol: "AAPL", type: "stock"});
    });

    it("forwards the abort signal and the token", async () => {
        store.set("token", "abc");
        fetchMock.mockResolvedValue(respond(200, {status: "ok"}));
        const controller = new AbortController();

        await api.getAnalystReport({symbol: "AAPL", type: "stock"}, {signal: controller.signal});
        const init = fetchMock.mock.calls[0][1];
        expect(init.signal).toBe(controller.signal);
        expect(init.headers.Authorization).toBe("Bearer abc");
    });

    it("rethrows aborts instead of reporting a connection problem", async () => {
        fetchMock.mockRejectedValue(new DOMException("The operation was aborted.", "AbortError"));
        await expect(api.getAnalystReport({symbol: "AAPL", type: "stock"})).rejects.toMatchObject({name: "AbortError"});
    });

    it("keeps the status and readable detail of errors such as 429", async () => {
        fetchMock.mockResolvedValue(respond(429, {detail: "You can refresh this analysis again in 4 minutes."}));
        await expect(api.getAnalystReport({symbol: "AAPL", type: "stock", refresh: true})).rejects.toMatchObject({
            status: 429, message: "You can refresh this analysis again in 4 minutes.",
        });
    });

    it("uses a readable fallback for server errors", async () => {
        fetchMock.mockResolvedValue(respond(503, new SyntaxError("not json")));
        await expect(api.getAnalystReport({symbol: "AAPL", type: "stock"}))
            .rejects.toThrow("Couldn't load the market analysis.");
    });
});

describe("deleteAccount", () => {
    it("sends an authenticated DELETE to /user with the current password", async () => {
        store.set("token", "abc");
        fetchMock.mockResolvedValue(respond(200, {message: "Account deleted"}));

        await expect(api.deleteAccount("my-password")).resolves.toEqual({message: "Account deleted"});
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/user`);
        expect(options.method).toBe("DELETE");
        expect(options.headers.Authorization).toBe("Bearer abc");
        expect(JSON.parse(options.body)).toEqual({current_password: "my-password"});
    });

    it("shows a wrong password without signing the user out", async () => {
        store.set("token", "abc");
        fetchMock.mockResolvedValue(respond(400, {detail: "Your current password is incorrect."}));
        await expect(api.deleteAccount("nope")).rejects.toThrow("Your current password is incorrect.");
        expect(store.get("token")).toBe("abc");
    });

    it("shows a readable error when the server fails", async () => {
        fetchMock.mockResolvedValue(respond(500, new Error("not json")));
        await expect(api.deleteAccount()).rejects.toThrow("Couldn't delete your account. Please try again.");
    });
});

describe("password reset", () => {
    it("asks for a reset email without needing a login", async () => {
        fetchMock.mockResolvedValue(respond(202, null));
        await api.forgotPassword("  a@b.co ");
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/auth/forgot-password`);
        expect(JSON.parse(options.body)).toEqual({email: "a@b.co"});
        expect(options.headers.Authorization).toBeUndefined();
    });

    it("explains an expired or used reset link", async () => {
        fetchMock.mockResolvedValue(respond(400, {detail: "RESET_PASSWORD_BAD_TOKEN"}));
        await expect(api.resetPassword("tok", "Long-enough-1"))
            .rejects.toThrow("This reset link is invalid or has expired. Request a new one.");
    });

    it("shows the password rule the server rejected", async () => {
        fetchMock.mockResolvedValue(respond(400, {
            detail: {code: "RESET_PASSWORD_INVALID_PASSWORD", reason: "Password must be at least 8 characters."},
        }));
        await expect(api.resetPassword("tok", "short")).rejects.toThrow("Password must be at least 8 characters.");
    });
});

describe("account security", () => {
    it("sends the current password with an email change", async () => {
        store.set("token", "abc");
        fetchMock.mockResolvedValue(respond(200, {message: "Verification email sent"}));
        await api.putUserEmail("  new@b.co ", "pw");
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/user/email`);
        expect(options.method).toBe("PUT");
        expect(JSON.parse(options.body)).toEqual({email: "new@b.co", current_password: "pw"});
    });

    it("changes the password and keeps this device signed in with the new token", async () => {
        store.set("token", "old");
        fetchMock.mockResolvedValue(respond(200, {message: "Password changed", access_token: "fresh"}));
        await api.changePassword("current-pw", "new-password-1");
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/user/password`);
        expect(options.method).toBe("POST");
        expect(options.headers.Authorization).toBe("Bearer old");
        expect(options.headers["X-Zenith-Client"]).toBeUndefined(); // website: normal one-hour token
        expect(JSON.parse(options.body)).toEqual({current_password: "current-pw", new_password: "new-password-1"});
        expect(store.get("token")).toBe("fresh");
    });

    it("logs out of all devices", async () => {
        store.set("token", "abc");
        fetchMock.mockResolvedValue(respond(200, {message: "Signed out of all devices"}));
        await api.logoutAllDevices();
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/user/logout-all`);
        expect(options.method).toBe("POST");
        expect(options.headers.Authorization).toBe("Bearer abc");
    });

    it.each([
        ["login", () => api.loginAuthentication({email: "a@b.co", password: "x"})],
        ["forgot password", () => api.forgotPassword("a@b.co")],
        ["resend verification", () => api.requestVerification("a@b.co")],
    ])("shows the rate limit message on %s", async (_, call) => {
        const detail = "Too many failed sign-in attempts for this account. Please wait 15 minutes or use Forgot password.";
        fetchMock.mockResolvedValue(respond(429, {detail}));
        await expect(call()).rejects.toThrow(detail);
    });

    it("has a readable 429 message even without a body (e.g. nginx's own limit)", async () => {
        fetchMock.mockResolvedValue(respond(429, new SyntaxError("not json")));
        await expect(api.forgotPassword("a@b.co")).rejects.toThrow("Too many attempts. Please wait a few minutes");
    });

    it("doesn't ask for a long-lived token on the website", async () => {
        fetchMock.mockResolvedValue(respond(200, {access_token: "abc"}));
        await api.loginAuthentication({email: "a@b.co", password: "x"});
        expect(fetchMock.mock.calls[0][1].headers["X-Zenith-Client"]).toBeUndefined();
    });
});

describe("in the iPhone app", () => {
    beforeEach(async () => {
        vi.resetModules();
        vi.doMock("../src/native/platform.js", () => ({isNative: true, loadPlugin: () => async () => ({})}));
        vi.doMock("../src/native/secureToken.js", () => ({saveToken: () => {}}));
        vi.doMock("../src/native/offlineCache.js", () => ({
            forgetAll: () => {}, recall: () => undefined, remember: () => {}, cacheTicket: () => ({}),
        }));
        api = await import("../src/services/api.js");
    });

    afterEach(() => {
        vi.doUnmock("../src/native/platform.js");
        vi.doUnmock("../src/native/secureToken.js");
        vi.doUnmock("../src/native/offlineCache.js");
    });

    it("asks for the app's long-lived token when logging in", async () => {
        fetchMock.mockResolvedValue(respond(200, {access_token: "abc"}));
        await api.loginAuthentication({email: "a@b.co", password: "x"});
        expect(fetchMock.mock.calls[0][1].headers["X-Zenith-Client"]).toBe("ios-app");
    });

    it("keeps the long-lived token after changing the password", async () => {
        store.set("token", "old");
        fetchMock.mockResolvedValue(respond(200, {access_token: "fresh"}));
        await api.changePassword("a", "b");
        const {headers} = fetchMock.mock.calls[0][1];
        expect(headers["X-Zenith-Client"]).toBe("ios-app");
        expect(headers.Authorization).toBe("Bearer old");
    });
});
