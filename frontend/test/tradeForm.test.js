import {describe, expect, it} from "vitest";
import {
    createPayload,
    isFutureInput,
    ledgerErrorMessage,
    localInputToIso,
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
