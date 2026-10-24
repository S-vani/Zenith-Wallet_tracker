import {describe, expect, it} from "vitest";
import {averageCost, holdingsTotals, isPriced} from "../src/Holdings/holdingsTotals.js";
import {sortTransactions, TRANSACTION_SORTS} from "../src/Transactions/transactionSort.js";

describe("averageCost", () => {
    it("is the cost basis over the quantity", () => {
        expect(averageCost({price_paid: 1550, quantity: 10})).toBe(155);
        expect(averageCost({price_paid: 0.0005, quantity: 1000})).toBeCloseTo(0.0000005);
    });

    it("is null without a quantity or cost", () => {
        expect(averageCost({price_paid: 100, quantity: 0})).toBeNull();
        expect(averageCost({price_paid: undefined, quantity: 2})).toBeNull();
    });
});

describe("holdingsTotals", () => {
    const aapl = {symbol: "AAPL", price_paid: 1000, current_price: 1200, quantity: 5};
    const btc = {symbol: "btc", price_paid: 500, current_price: 400, quantity: 0.01};
    const pepe = {symbol: "pepe", price_paid: 50, current_price: null, quantity: 1e6};

    it("sums value and return over priced holdings", () => {
        const t = holdingsTotals([aapl, btc]);
        expect(t.value).toBe(1600);
        expect(t.cost).toBe(1500);
        expect(t.gain).toBe(100);
        expect(t.gainPct).toBeCloseTo(6.6667, 3);
        expect(t.unpriced).toEqual([]);
    });

    it("leaves unpriced holdings out and names them", () => {
        expect(isPriced(pepe)).toBe(false);
        const t = holdingsTotals([aapl, pepe]);
        expect(t.value).toBe(1200);
        expect(t.gain).toBe(200);
        expect(t.gainPct).toBe(20);
        expect(t.unpriced).toEqual(["PEPE"]);
    });

    it("has no totals when nothing is priced", () => {
        expect(holdingsTotals([pepe])).toEqual({value: null, cost: null, gain: null, gainPct: null, unpriced: ["PEPE"]});
    });

    it("has no return % on a zero cost basis", () => {
        const t = holdingsTotals([{symbol: "GIFT", price_paid: 0, current_price: 10, quantity: 1}]);
        expect(t.gain).toBe(10);
        expect(t.gainPct).toBeNull();
    });
});

describe("sortTransactions", () => {
    const trades = [
        {id: 1, created_at: "2024-01-01T10:00:00", price_of_one: 10, quantity: 1},
        {id: 2, created_at: "2024-03-01T10:00:00", price_of_one: 2, quantity: 3},
        {id: 3, created_at: "2024-02-01T10:00:00", price_of_one: 100, quantity: 0.5},
        {id: 4, created_at: "2024-04-01T10:00:00", price_of_one: 25, quantity: 2},
    ];
    const ids = (list) => list.map((t) => t.id);

    it("offers the three sorts", () => {
        expect(TRANSACTION_SORTS.map((s) => s.value)).toEqual(["newest", "oldest", "amount"]);
    });

    it("sorts newest first by default", () => {
        expect(ids(sortTransactions(trades))).toEqual([4, 2, 3, 1]);
        expect(ids(sortTransactions(trades, "unknown"))).toEqual([4, 2, 3, 1]);
    });

    it("sorts oldest first", () => {
        expect(ids(sortTransactions(trades, "oldest"))).toEqual([1, 3, 2, 4]);
    });

    it("sorts by total amount, newest first on ties", () => {
        // totals: 10, 6, 50, 50
        expect(ids(sortTransactions(trades, "amount"))).toEqual([4, 3, 1, 2]);
    });

    it("doesn't change the array it was given", () => {
        const copy = [...trades];
        sortTransactions(trades, "oldest");
        expect(trades).toEqual(copy);
    });
});
