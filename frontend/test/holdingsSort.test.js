import {describe, expect, it} from "vitest";
import {sortHoldings} from "../src/Holdings/holdingsSort.js";

const h = (symbol, current_price, price_paid, day_change_pct) => ({symbol, current_price, price_paid, day_change_pct});
const list = [h("MSFT", 300, 200, 1), h("AAPL", 500, 400, -2), h("BTC", null, 100, null), h("SOL", 100, 200, 5)];
const order = (sort) => sortHoldings(list, sort).map((x) => x.symbol);

describe("holdings sort", () => {
    it("orders by value, today, return and name, unknowns last", () => {
        expect(order("value")).toEqual(["AAPL", "MSFT", "SOL", "BTC"]);
        expect(order("today")).toEqual(["SOL", "MSFT", "AAPL", "BTC"]);
        expect(order("return")).toEqual(["MSFT", "AAPL", "SOL", "BTC"]);
        expect(order("name")).toEqual(["AAPL", "BTC", "MSFT", "SOL"]);
        expect(order("nonsense")).toEqual(order("value"));
    });
});
