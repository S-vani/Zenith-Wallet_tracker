import {describe, expect, it} from "vitest";
import {
    amountHint,
    createPayload,
    isFutureInput,
    ledgerErrorMessage,
    localInputToIso,
    parseDecimalInput,
    quantityInputValue,
    symbolSelection,
    toLocalInputValue,
    updatePayload,
} from "../src/Transactions/tradeForm.js";

// test/setup.js pins the time zone to America/Toronto (UTC-5 in winter, UTC-4 in summer)

describe("trade dates", () => {
    it("shows a UTC timestamp as local datetime-local text", () => {
        expect(toLocalInputValue("2024-01-10T17:05:00+00:00")).toBe("2024-01-10T12:05");
        expect(toLocalInputValue("2024-07-01T03:30:00Z")).toBe("2024-06-30T23:30");
        expect(toLocalInputValue("not a date")).toBe("");
    });

    it("sends the local time as UTC, like the date filters", () => {
        expect(localInputToIso("2024-01-10T12:05")).toBe("2024-01-10T17:05:00.000Z");
        expect(localInputToIso("2024-06-30T23:30")).toBe("2024-07-01T03:30:00.000Z");
        expect(localInputToIso("")).toBeNull();
        expect(localInputToIso("garbage")).toBeNull();
    });

    it("round-trips", () => {
        expect(localInputToIso(toLocalInputValue("2025-03-09T07:00:00Z"))).toBe("2025-03-09T07:00:00.000Z");
    });

    it("spots future dates", () => {
        const now = new Date("2026-10-18T12:00:00Z");
        expect(isFutureInput("2026-10-18T08:00", now)).toBe(false); // 12:00 UTC exactly
        expect(isFutureInput("2026-10-18T08:01", now)).toBe(true);
        expect(isFutureInput("", now)).toBe(false);
    });
});

describe("payloads", () => {
    const form = {
        symbol: "AAPL", api_id: "AAPL", asset_type: "stock", action: "SELL",
        quantity: "72973129.312", price_of_one: "100.5", created_at: "2026-10-18T09:00",
    };

    it("leaves the date out of a new trade unless it was changed", () => {
        const body = createPayload(form, "2026-10-18T09:00");
        expect(body).toEqual({
            symbol: "AAPL", api_id: "AAPL", asset_type: "stock", action: "SELL",
            quantity: 72973129.312, price_of_one: 100.5,
        });
        expect(createPayload({...form, created_at: ""}, "2026-10-18T09:00")).not.toHaveProperty("created_at");
    });

    it("sends a coin's CoinGecko id, and none for stocks or when search had none", () => {
        const coin = {...form, symbol: "pepe", api_id: "pepe", asset_type: "crypto", coin_id: "pepe-impostor"};
        expect(createPayload(coin, "2026-10-18T09:00").coin_id).toBe("pepe-impostor");
        expect(createPayload({...coin, coin_id: null}, "2026-10-18T09:00")).not.toHaveProperty("coin_id");
        expect(createPayload({...form, coin_id: "apple"}, "2026-10-18T09:00")).not.toHaveProperty("coin_id");
    });

    it("sends a changed date as UTC", () => {
        const body = createPayload({...form, created_at: "2026-01-02T10:00"}, "2026-10-18T09:00");
        expect(body.created_at).toBe("2026-01-02T15:00:00.000Z");
    });

    it("sends only the fields an edit changed", () => {
        const initial = {action: "BUY", quantity: "2", price_of_one: "100", created_at: "2024-01-10T12:05"};
        expect(updatePayload(initial, {...initial})).toEqual({});
        expect(updatePayload(initial, {...initial, quantity: "3"})).toEqual({quantity: 3});
        expect(updatePayload(initial, {...initial, action: "SELL", price_of_one: "120.25"}))
            .toEqual({action: "SELL", price_of_one: 120.25});
        expect(updatePayload(initial, {...initial, created_at: "2024-01-09T12:05"}))
            .toEqual({created_at: "2024-01-09T17:05:00.000Z"});
        expect(updatePayload(initial, {...initial, created_at: ""})).toEqual({}); // cleared = unchanged
    });
});

describe("decimal input", () => {
    it("reads a decimal comma or point the same way", () => {
        expect(parseDecimalInput("1,5")).toBe(1.5);
        expect(parseDecimalInput("1.5")).toBe(1.5);
        expect(parseDecimalInput(" 0,000125 ")).toBe(0.000125);
        expect(parseDecimalInput(",5")).toBe(0.5);
        expect(parseDecimalInput(".5")).toBe(0.5);
        expect(parseDecimalInput("5,")).toBe(5);
        expect(parseDecimalInput("42")).toBe(42);
        expect(parseDecimalInput("0")).toBe(0);
    });

    it("rejects thousands separators, several separators and anything else", () => {
        for (const text of ["", " ", "1,234.5", "1.234,5", "1.2.3", "1,,5", ",", ".", "1e5", "-1", "+1", "abc",
            "1 000", "$5", null, undefined]) {
            expect(parseDecimalInput(text), String(text)).toBeNaN();
        }
    });

    it("explains a typed value that isn't a positive number", () => {
        expect(amountHint("", "")).toBeNull();
        expect(amountHint("1,5", "100.25")).toBeNull();
        expect(amountHint("1,5", "")).toBeNull();
        expect(amountHint("1,234.5", "")).toMatch(/numbers only/);
        expect(amountHint("2", "abc")).toMatch(/numbers only/);
        expect(amountHint("0", "10")).toBe("Quantity and price must both be greater than 0.");
        expect(amountHint("1", "0,00")).toBe("Quantity and price must both be greater than 0.");
    });

    it("prefills quantities without exponents or float noise", () => {
        expect(quantityInputValue(0.0000001)).toBe("0.0000001");
        expect(quantityInputValue(2)).toBe("2");
        expect(quantityInputValue(1.5)).toBe("1.5");
        expect(quantityInputValue(0.1 + 0.2)).toBe("0.3");
        expect(quantityInputValue(1e9)).toBe("1000000000");
        expect(quantityInputValue("abc")).toBe("");
        expect(parseDecimalInput(quantityInputValue(0.0000001))).toBe(0.0000001);
    });

    it("sends what was typed with a comma as a number", () => {
        const form = {symbol: "BTC", api_id: "btc", asset_type: "crypto", action: "BUY", quantity: "0,5",
            price_of_one: "95000,25", created_at: ""};
        expect(createPayload(form, "")).toMatchObject({quantity: 0.5, price_of_one: 95000.25});
        const initial = {action: "BUY", quantity: "2", price_of_one: "100", created_at: ""};
        expect(updatePayload(initial, {...initial, quantity: "2,5"})).toEqual({quantity: 2.5});
    });
});

describe("ledger errors", () => {
    const conflict = Object.assign(new Error("Insufficient holdings"), {status: 409});

    it("passes other errors through", () => {
        expect(ledgerErrorMessage(new Error("Can't reach the server."), {mode: "edit"})).toBe("Can't reach the server.");
    });

    it("explains a 409 for each action", () => {
        expect(ledgerErrorMessage(conflict, {mode: "create", symbol: "aapl", action: "SELL"}))
            .toBe("You can't sell more AAPL than you own.");
        expect(ledgerErrorMessage(conflict, {mode: "create", symbol: "aapl", action: "SELL", backdated: true}))
            .toMatch(/didn't own that much AAPL on that date/);
        expect(ledgerErrorMessage(conflict, {mode: "edit", symbol: "btc"})).toMatch(/BTC history selling more/);
        expect(ledgerErrorMessage(conflict, {mode: "delete", symbol: "eth"}))
            .toMatch(/can't be deleted: a later sell of ETH needs it/);
    });
});

describe("picking a search result", () => {
    // regression: the Select button dropped coin_id, so a coin sharing its ticker was saved as the popular one
    it("keeps a coin's CoinGecko id through to the saved trade", () => {
        const result = {api_id: "pepe", symbol: "pepe", type: "crypto", price: 0.00001, coin_id: "pepe-impostor",
            name: "Pepe Impostor", change: 0, change_pct: 0};
        const picked = symbolSelection(result);
        expect(picked).toEqual({api_id: "pepe", symbol: "pepe", type: "crypto", price: 0.00001,
            coin_id: "pepe-impostor"});

        // what TransactionCreate builds from it, then sends
        const form = {symbol: picked.symbol, api_id: picked.api_id, coin_id: picked.coin_id ?? null,
            asset_type: picked.type, action: "BUY", quantity: "1", price_of_one: "1", created_at: "x"};
        expect(createPayload(form, "x").coin_id).toBe("pepe-impostor");
    });

    it("sends no coin id for stocks or coins without one", () => {
        expect(symbolSelection({api_id: "SHOP.TO", symbol: "SHOP.TO", type: "stock", price: 100, coin_id: "x"}))
            .not.toHaveProperty("coin_id");
        expect(symbolSelection({api_id: "btc", symbol: "btc", type: "crypto", price: 1})).not.toHaveProperty("coin_id");
    });
});
