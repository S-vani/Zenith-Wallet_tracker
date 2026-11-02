import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {
    hasScanConsent, isImageFile, pickSearchMatch, saveScanConsent, scanInputDate, scanNotes, scanPrefill,
    scanSearchQuery, scanTradeDay, scanTradeLabel, shrinkImage,
} from "../src/Transactions/scanHelpers.js";

// "Scan a screenshot" in the add-trade dialog. The time zone is pinned to America/Toronto (test/setup.js), which is
// still on EDT (UTC−4) on 2026-10-30.

// a trade as POST /transactions/scan returns it, with the fields each test cares about changed
function trade(changes = {}) {
    return {
        action: "BUY", asset_type: "stock", symbol: "SHOP.TO", name: "Shopify Inc.", quantity: 10, price: 150.25,
        currency: "CAD", price_in_user_currency: 150.25, converted: false, date: "2026-10-30T14:05:00",
        date_only: false, account_type: "TFSA", confidence: "high", notes: [], ...changes,
    };
}

const NOW = new Date("2026-11-01T15:30:00Z"); // 10:30 in Toronto (EST from today)

describe("pickSearchMatch", () => {
    const stocks = [
        {api_id: "SHOP", symbol: "SHOP", type: "stock", exchange: "NYSE"},
        {api_id: "SHOP.TO", symbol: "SHOP", type: "stock", exchange: "TSX"},
    ];

    it("picks the exact listing of a stock by its Yahoo ticker, ignoring case", () => {
        expect(pickSearchMatch(stocks, trade({symbol: "shop.to"}))).toBe(stocks[1]);
        expect(pickSearchMatch(stocks, trade({symbol: "SHOP"}))).toBe(stocks[0]);
    });

    it("matches class shares written the Yahoo way", () => {
        const results = [{api_id: "BRK-A", type: "stock"}, {api_id: "BRK-B", type: "stock"}];
        expect(pickSearchMatch(results, trade({symbol: "BRK-B"}))).toBe(results[1]);
    });

    it("matches a coin by its ticker (the first, most popular, of coins sharing it)", () => {
        const coins = [
            {api_id: "btc", symbol: "BTC", coin_id: "bitcoin", type: "crypto"},
            {api_id: "btc", symbol: "BTC", coin_id: "bitcoin-token", type: "crypto"},
        ];
        expect(pickSearchMatch(coins, trade({asset_type: "crypto", symbol: "btc"}))).toBe(coins[0]);
        expect(pickSearchMatch(coins, trade({asset_type: "crypto", symbol: "BTC"}))).toBe(coins[0]);
    });

    it("is null when nothing matches exactly", () => {
        expect(pickSearchMatch(stocks, trade({symbol: "SHOP.V"}))).toBeNull();
        expect(pickSearchMatch(stocks, trade({symbol: ""}))).toBeNull();
        expect(pickSearchMatch([], trade())).toBeNull();
        expect(pickSearchMatch(null, trade())).toBeNull();
        expect(pickSearchMatch(stocks, null)).toBeNull();
    });

    it("doesn't take a coin for a stock with the same ticker", () => {
        const results = [{api_id: "link", symbol: "LINK", type: "crypto"}];
        expect(pickSearchMatch(results, trade({symbol: "LINK"}))).toBeNull();
    });
});

describe("scanSearchQuery", () => {
    it("searches stocks by the bare ticker and coins by the lowercase ticker", () => {
        expect(scanSearchQuery(trade({symbol: "XEQT.TO"}))).toBe("XEQT");
        expect(scanSearchQuery(trade({symbol: "BRK-B"}))).toBe("BRK");
        expect(scanSearchQuery(trade({symbol: "AAPL"}))).toBe("AAPL");
        expect(scanSearchQuery(trade({asset_type: "crypto", symbol: "ETH"}))).toBe("eth");
    });
});

describe("scanPrefill", () => {
    it("fills the form from the scanned trade, the date in local time", () => {
        expect(scanPrefill(trade(), NOW)).toEqual({
            action: "BUY", quantity: "10", price_of_one: "150.25", created_at: "2026-10-30T10:05", account_type: "TFSA",
        });
    });

    it("uses the price already converted to the user's currency", () => {
        const prefill = scanPrefill(trade({price: 100, currency: "USD", price_in_user_currency: 137.456, converted: true}), NOW);
        expect(prefill.price_of_one).toBe("137.46");
        const coin = scanPrefill(trade({asset_type: "crypto", price_in_user_currency: 0.00001234}), NOW);
        expect(coin.price_of_one).toBe("0.00001234");
    });

    it("leaves out whatever couldn't be read", () => {
        const prefill = scanPrefill(trade({
            quantity: null, price: null, price_in_user_currency: null, date: null, account_type: null,
        }), NOW);
        expect(prefill).toEqual({action: "BUY", account_type: ""});
        expect(prefill).not.toHaveProperty("quantity");
        expect(prefill).not.toHaveProperty("price_of_one");
        expect(prefill).not.toHaveProperty("created_at"); // the form keeps its "now"
    });

    it("never prefills a zero or an unknown action", () => {
        const prefill = scanPrefill(trade({quantity: 0, price_in_user_currency: 0, action: "TRANSFER"}), NOW);
        expect(prefill).toEqual({created_at: "2026-10-30T10:05", account_type: "TFSA"});
    });

    it("writes tiny quantities without an exponent", () => {
        expect(scanPrefill(trade({quantity: 0.0000001}), NOW).quantity).toBe("0.0000001");
    });

    it.each([
        ["TFSA", "TFSA"],
        ["NON_REGISTERED", "NON_REGISTERED"],
        [null, ""],
        ["MARGIN", ""],
    ])("maps the account %s to %j", (account, value) => {
        expect(scanPrefill(trade({account_type: account}), NOW).account_type).toBe(value);
    });

    it("takes a sell as a sell", () => {
        expect(scanPrefill(trade({action: "SELL"}), NOW).action).toBe("SELL");
    });
});

describe("scanInputDate", () => {
    it("reads the naive UTC date as UTC, also across the time change", () => {
        expect(scanInputDate(trade({date: "2026-11-02T14:05:00"}), NOW)).toBe("2026-11-02T09:05"); // EST
        expect(scanInputDate(trade({date: "2026-10-30T02:00:00"}), NOW)).toBe("2026-10-29T22:00"); // evening before
        expect(scanInputDate(trade({date: "2026-10-30T14:05:00Z"}), NOW)).toBe("2026-10-30T10:05");
    });

    it("keeps the calendar day of a date without a time", () => {
        expect(scanInputDate(trade({date: "2026-10-28T00:00:00", date_only: true}), NOW)).toBe("2026-10-28T12:00");
        expect(scanInputDate(trade({date: "2026-10-28", date_only: true}), NOW)).toBe("2026-10-28T12:00");
        // today's: now, so it's never in the future
        expect(scanInputDate(trade({date: "2026-11-01T00:00:00", date_only: true}), NOW)).toBe("2026-11-01T10:30");
    });

    it("is null without a usable date", () => {
        expect(scanInputDate(trade({date: null}), NOW)).toBeNull();
        expect(scanInputDate(trade({date: "yesterday"}), NOW)).toBeNull();
        expect(scanInputDate(trade({date: "nope", date_only: true}), NOW)).toBeNull();
    });
});

describe("scanNotes", () => {
    const FIRST = "Filled in from your screenshot. Check every field before saving it.";

    it("starts by saying where the values came from", () => {
        expect(scanNotes(trade(), "CAD")).toEqual([FIRST]);
    });

    it("says a price was converted, with the amount as shown", () => {
        const notes = scanNotes(trade({price: 123.45, currency: "USD", price_in_user_currency: 170, converted: true}), "CAD");
        expect(notes).toContain("Price converted from US$123.45 at that day's exchange rate.");
        const euros = scanNotes(trade({price: 9.5, currency: "EUR", price_in_user_currency: 10.2, converted: true, date: null}), "USD");
        expect(euros).toContain("Price converted from €9.50 at today's exchange rate.");
    });

    it("says when a price couldn't be converted or read", () => {
        expect(scanNotes(trade({price: 50, currency: "USD", price_in_user_currency: null, converted: false}), "CAD"))
            .toContain("The screenshot shows a price of US$50.00, which couldn't be converted. Enter the price in CAD.");
        expect(scanNotes(trade({price: null, price_in_user_currency: null}), "CAD"))
            .toContain("Couldn't read the price. Enter it yourself.");
    });

    it("says what's missing about the quantity and the date", () => {
        const notes = scanNotes(trade({quantity: null, date: null}), "CAD");
        expect(notes).toContain("Couldn't read the quantity. Enter it yourself.");
        expect(notes).toContain("No date was found, so it's set to now.");
        expect(scanNotes(trade({date_only: true}), "CAD")).toContain("The screenshot only shows the day, so check the time.");
    });

    it("says when the screenshot was read on this device", () => {
        expect(scanNotes(trade({onDevice: true}), "CAD")).toEqual([FIRST, "Read on this device."]);
        expect(scanNotes(trade({onDevice: true, confidence: "low"}), "CAD")).toEqual([
            FIRST, "Read on this device.", "Confidence: low — double-check the amounts.",
        ]);
    });

    it("warns about a low confidence read only", () => {
        expect(scanNotes(trade({confidence: "low"}), "CAD")).toContain("Confidence: low — double-check the amounts.");
        expect(scanNotes(trade({confidence: "medium"}), "CAD")).toEqual([FIRST]);
    });

    it("adds the reader's own notes, once each, skipping empty ones", () => {
        const notes = scanNotes(trade({notes: ["Fees of CA$4.95 not included.", "", "Fees of CA$4.95 not included.", 3]}), "CAD");
        expect(notes).toEqual([FIRST, "Fees of CA$4.95 not included."]);
    });
});

describe("scanTradeLabel / scanTradeDay", () => {
    it("names each trade of a screenshot with several", () => {
        expect(scanTradeLabel(trade({symbol: "XEQT.TO"}))).toBe("Buy 10 XEQT.TO");
        expect(scanTradeLabel(trade({action: "SELL", asset_type: "crypto", symbol: "btc", quantity: 0.05})))
            .toBe("Sell 0.05 BTC");
        expect(scanTradeLabel(trade({quantity: null}))).toBe("Buy SHOP.TO");
    });

    it("gives the local day, or nothing", () => {
        expect(scanTradeDay(trade(), NOW)).toBe("Oct 30, 2026");
        expect(scanTradeDay(trade({date: null}), NOW)).toBe("");
    });
});

describe("files and consent", () => {
    it("knows an image by its type, or its name when there's no type", () => {
        expect(isImageFile({type: "image/png", name: "a.png"})).toBe(true);
        expect(isImageFile({type: "", name: "IMG_0001.HEIC"})).toBe(true);
        expect(isImageFile({type: "application/pdf", name: "a.pdf"})).toBe(false);
        expect(isImageFile({type: "", name: "notes.txt"})).toBe(false);
        expect(isImageFile(null)).toBe(false);
    });

    it("refuses non-images and huge files before decoding anything", async () => {
        await expect(shrinkImage({type: "application/pdf", name: "a.pdf", size: 10}))
            .rejects.toThrow("That file isn't an image.");
        await expect(shrinkImage({type: "image/jpeg", name: "a.jpg", size: 21 * 1024 * 1024}))
            .rejects.toThrow("That image is over 20 MB.");
    });

    it("remembers the yes on this device, and copes without storage", () => {
        const store = new Map();
        vi.stubGlobal("localStorage", {
            getItem: (k) => (store.has(k) ? store.get(k) : null),
            setItem: (k, v) => store.set(k, String(v)),
        });
        expect(hasScanConsent()).toBe(false);
        saveScanConsent();
        expect(store.get("scanConsent")).toBe("yes");
        expect(hasScanConsent()).toBe(true);

        vi.stubGlobal("localStorage", {
            getItem: () => {
                throw new Error("blocked");
            },
            setItem: () => {
                throw new Error("blocked");
            },
        });
        expect(hasScanConsent()).toBe(false);
        expect(() => saveScanConsent()).not.toThrow();
        vi.unstubAllGlobals();
    });
});

describe("scanTradeScreenshot / scanTradeFields / getScanOptions", () => {
    // same setup as api.test.js: api.js reads the backend url at import time, so import it fresh per test
    const BASE = "http://api.test";
    let api;
    let fetchMock;
    let store;
    let events;

    function respond(status, body, headers = {}) {
        return {
            ok: status >= 200 && status < 300,
            status,
            headers: {get: (name) => headers[name] ?? null},
            json: async () => {
                if (body instanceof Error) throw body;
                return body;
            },
        };
    }

    const image = () => new Blob(["fake jpeg"], {type: "image/jpeg"});

    beforeEach(async () => {
        vi.resetModules();
        vi.stubEnv("VITE_BACKEND_URL", BASE);
        store = new Map([["token", "abc"]]);
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

    it("POSTs the image as multipart with the token and no JSON content type", async () => {
        fetchMock.mockResolvedValue(respond(200, {trades: [trade()], warnings: []}));
        await api.scanTradeScreenshot(image());

        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/transactions/scan`);
        expect(options.method).toBe("POST");
        expect(options.body).toBeInstanceOf(FormData);
        const sent = options.body.get("image");
        expect(sent).toBeInstanceOf(Blob);
        expect(sent.name).toBe("screenshot.jpg");
        expect(await sent.text()).toBe("fake jpeg");
        expect(options.headers.Authorization).toBe("Bearer abc");
        // the browser writes multipart/form-data with its boundary itself
        expect(Object.keys(options.headers).map((k) => k.toLowerCase())).not.toContain("content-type");
    });

    it("keeps the file's own name when it has one", async () => {
        fetchMock.mockResolvedValue(respond(200, {trades: []}));
        await api.scanTradeScreenshot(new File(["x"], "IMG_0001.HEIC", {type: "image/heic"}));
        expect(fetchMock.mock.calls[0][1].body.get("image").name).toBe("IMG_0001.HEIC");
    });

    it("returns the trades and warnings, dropping anything malformed", async () => {
        fetchMock.mockResolvedValue(respond(200, {trades: [trade(), null, "x"], warnings: ["Two pages?", 4]}));
        await expect(api.scanTradeScreenshot(image())).resolves.toEqual({trades: [trade()], warnings: ["Two pages?"]});
        fetchMock.mockResolvedValue(respond(200, {}));
        await expect(api.scanTradeScreenshot(image())).resolves.toEqual({trades: [], warnings: []});
    });

    it("shows the server's detail as it is", async () => {
        const detail = "Couldn't find a buy or sell in this screenshot. Try one that shows the order details.";
        fetchMock.mockResolvedValue(respond(422, {detail}));
        await expect(api.scanTradeScreenshot(image())).rejects.toMatchObject({status: 422, message: detail});
    });

    it("keeps a rate limit's detail and wait", async () => {
        fetchMock.mockResolvedValue(respond(429, {detail: "Please wait a minute before scanning again."}, {"Retry-After": "60"}));
        await expect(api.scanTradeScreenshot(image())).rejects.toMatchObject({
            status: 429, message: "Please wait a minute before scanning again.", retryAfter: 60,
        });
    });

    it.each([
        [413, "That image is too large."],
        [415, "That file type isn't supported."],
        [429, "Too many attempts."],
        [502, "Couldn't read the screenshot right now."],
        [503, "Screenshot import isn't available right now."],
        [500, "Couldn't read the screenshot. Please try again"],
    ])("has a readable message for a %i without a detail (e.g. nginx's own page)", async (status, message) => {
        fetchMock.mockResolvedValue(respond(status, new SyntaxError("not json")));
        await expect(api.scanTradeScreenshot(image())).rejects.toThrow(message);
    });

    it.each([
        [413, "Screenshots can be up to 2.5 MB."],
        [415, "Use a PNG, JPEG, WebP or HEIC image."],
        [502, "Couldn't read the screenshot right now. Please try again in a minute."],
        [503, "Screenshot import isn't available right now."],
    ])("passes the server's %i detail through", async (status, detail) => {
        fetchMock.mockResolvedValue(respond(status, {detail}));
        await expect(api.scanTradeScreenshot(image())).rejects.toMatchObject({status, message: detail});
    });

    it("signs out when the token it was sent with has expired", async () => {
        fetchMock.mockResolvedValue(respond(401, {detail: "Unauthorized"}));
        await expect(api.scanTradeScreenshot(image())).rejects.toThrow("Your session has expired.");
        expect(store.has("token")).toBe(false);
        expect(events).toContain("auth:expired");
    });

    it("doesn't sign out a newer session for an old token's 401", async () => {
        fetchMock.mockImplementation(async () => {
            store.set("token", "newer"); // someone signed in again while the scan was out
            return respond(403, {detail: "Forbidden"});
        });
        await expect(api.scanTradeScreenshot(image())).rejects.toThrow("Your session has expired.");
        expect(store.get("token")).toBe("newer");
        expect(events).not.toContain("auth:expired");
    });

    it("lets the caller ignore a cancelled scan", async () => {
        const controller = new AbortController();
        fetchMock.mockImplementation(async (url, options) => {
            expect(options.signal).toBe(controller.signal); // the website passes the caller's signal straight on
            throw new DOMException("aborted", "AbortError");
        });
        controller.abort();
        await expect(api.scanTradeScreenshot(image(), {signal: controller.signal})).rejects.toMatchObject({name: "AbortError"});
    });

    it("says when the server can't be reached", async () => {
        fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
        await expect(api.scanTradeScreenshot(image())).rejects.toThrow("Can't reach the server.");
    });

    // the free reading: only the fields read on the device are sent
    const fields = {
        action: "BUY", asset_type: "stock", symbol: "XEQT", exchange: "TSX", name: null, quantity: 10, price: 31.24,
        total: 312.4, currency: "CAD", date: "2026-10-30 14:05", timezone: "EDT", account_type: "TFSA",
        confidence: "high",
    };

    it("POSTs the fields read on the device as JSON, never an image", async () => {
        fetchMock.mockResolvedValue(respond(200, {trades: [trade()], warnings: ["Fees not included."]}));
        await expect(api.scanTradeFields([fields], {moreTrades: true})).resolves.toEqual({
            trades: [trade()], warnings: ["Fees not included."],
        });
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/transactions/scan/fields`);
        expect(options.method).toBe("POST");
        expect(options.headers["Content-Type"]).toBe("application/json");
        expect(options.headers.Authorization).toBe("Bearer abc");
        expect(JSON.parse(options.body)).toEqual({trades: [fields], more_trades: true});
    });

    it("sends more_trades false by default and drops anything malformed in the answer", async () => {
        fetchMock.mockResolvedValue(respond(200, {trades: [trade(), null, 7], warnings: [3, "One"]}));
        await expect(api.scanTradeFields([fields])).resolves.toEqual({trades: [trade()], warnings: ["One"]});
        expect(JSON.parse(fetchMock.mock.calls[0][1].body).more_trades).toBe(false);
        fetchMock.mockResolvedValue(respond(200, null));
        await expect(api.scanTradeFields(null)).resolves.toEqual({trades: [], warnings: []});
        expect(JSON.parse(fetchMock.mock.calls[1][1].body).trades).toEqual([]);
    });

    it("keeps the status of a refusal, so a 422 (no usable trade) can offer the next step", async () => {
        const detail = "Couldn't find a buy or sell in this screenshot.";
        fetchMock.mockResolvedValue(respond(422, {detail}));
        await expect(api.scanTradeFields([fields])).rejects.toMatchObject({status: 422, message: detail});
        fetchMock.mockResolvedValue(respond(429, {detail: "Please wait a minute."}));
        await expect(api.scanTradeFields([fields])).rejects.toMatchObject({status: 429});
    });

    it("lets the caller ignore a cancelled check", async () => {
        const controller = new AbortController();
        fetchMock.mockImplementation(async (url, options) => {
            expect(options.signal).toBe(controller.signal);
            throw new DOMException("aborted", "AbortError");
        });
        await expect(api.scanTradeFields([fields], {signal: controller.signal})).rejects.toMatchObject({name: "AbortError"});
    });

    it("reads whether the AI reading is on", async () => {
        fetchMock.mockResolvedValue(respond(200, {ai: true}));
        await expect(api.getScanOptions()).resolves.toEqual({ai: true});
        expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/transactions/scan/options`);
        expect(fetchMock.mock.calls[0][1].method).toBeUndefined(); // a GET
        fetchMock.mockResolvedValue(respond(200, {ai: "yes"}));
        await expect(api.getScanOptions()).resolves.toEqual({ai: false}); // only a real true counts
    });

    it.each([
        ["an error", () => respond(500, {detail: "boom"})],
        ["an older server without the route", () => respond(404, {detail: "Not Found"})],
        ["no connection", () => {
            throw new TypeError("Failed to fetch");
        }],
    ])("treats %s as AI reading off", async (_, reply) => {
        fetchMock.mockImplementation(async () => reply());
        await expect(api.getScanOptions()).resolves.toEqual({ai: false});
    });
});
