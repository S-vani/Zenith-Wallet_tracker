import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

// Same setup as api.test.js: api.js reads the backend url at import time, so import it fresh per test
const BASE = "http://api.test";
let api;
let fetchMock;

function respond(status, body) {
    return {ok: status >= 200 && status < 300, status, json: async () => body};
}

beforeEach(async () => {
    vi.resetModules();
    vi.stubEnv("VITE_BACKEND_URL", BASE);
    const store = new Map([["token", "abc"]]);
    vi.stubGlobal("localStorage", {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
        removeItem: (k) => store.delete(k),
    });
    vi.stubGlobal("window", {dispatchEvent: () => true});
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    api = await import("../src/services/api.js");
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

describe("updateTransaction", () => {
    it("PUTs only the changes, with the token", async () => {
        fetchMock.mockResolvedValue(respond(200, {id: "t/1"}));
        await api.updateTransaction("t/1", {quantity: 3});
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/transactions/t%2F1`);
        expect(options.method).toBe("PUT");
        expect(JSON.parse(options.body)).toEqual({quantity: 3});
        expect(options.headers.Authorization).toBe("Bearer abc");
    });

    it("keeps the status of a ledger conflict so the form can explain it", async () => {
        fetchMock.mockResolvedValue(respond(409, {detail: "Insufficient holdings"}));
        await expect(api.updateTransaction("t1", {quantity: 9})).rejects.toMatchObject({
            status: 409, message: "Insufficient holdings",
        });
    });

    it("names the date field in validation errors", async () => {
        fetchMock.mockResolvedValue(respond(422, {
            detail: [{loc: ["body", "created_at"], msg: "Value error, can't be in the future"}],
        }));
        await expect(api.updateTransaction("t1", {created_at: "2999-01-01T00:00:00Z"}))
            .rejects.toThrow("Date: can't be in the future");
    });
});

describe("deleteTransaction", () => {
    it("sends a DELETE for that trade", async () => {
        fetchMock.mockResolvedValue(respond(200, {id: "t1", deleted: true}));
        expect(await api.deleteTransaction("t1")).toEqual({id: "t1", deleted: true});
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(`${BASE}/transactions/t1`);
        expect(options.method).toBe("DELETE");
    });

    it("shows a readable error when the server fails", async () => {
        fetchMock.mockResolvedValue(respond(500, null));
        await expect(api.deleteTransaction("t1")).rejects.toThrow("Couldn't delete this trade. Please try again.");
    });
});

describe("getPriceHistory", () => {
    it("asks for the exact coin when its CoinGecko id is known", async () => {
        fetchMock.mockResolvedValue(respond(200, {data: []}));
        await api.getPriceHistory("pepe", "crypto", "5Y", "pepe-impostor");
        expect(fetchMock.mock.calls[0][0])
            .toBe(`${BASE}/prices/history?symbol=pepe&type=crypto&range=5Y&coin_id=pepe-impostor`);
    });

    it("leaves coin_id out for stocks and for coins without one", async () => {
        fetchMock.mockResolvedValue(respond(200, {data: []}));
        await api.getPriceHistory("AAPL", "stock", "1M", "apple");
        await api.getPriceHistory("btc", "crypto", "1M", null);
        expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
            `${BASE}/prices/history?symbol=AAPL&type=stock&range=1M`,
            `${BASE}/prices/history?symbol=btc&type=crypto&range=1M`,
        ]);
    });
});

describe("getTransactions", () => {
    it("passes the account filter, including UNSET for trades without one", async () => {
        fetchMock.mockResolvedValue(respond(200, []));
        await api.getTransactions({symbol: "", action: "BUY", account_type: "TFSA"});
        await api.getTransactions({account_type: "UNSET"});
        await api.getTransactions({account_type: ""});
        expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
            `${BASE}/transactions?action=BUY&account_type=TFSA`,
            `${BASE}/transactions?account_type=UNSET`,
            `${BASE}/transactions?`,
        ]);
    });
});

describe("createTransaction", () => {
    it("shows the symbol limit's message as is (it's not a ledger conflict)", async () => {
        fetchMock.mockResolvedValue(respond(422, {detail: "You can track up to 200 different assets."}));
        await expect(api.createTransaction({symbol: "X"})).rejects.toMatchObject({
            status: 422, message: "You can track up to 200 different assets.",
        });
    });
});
