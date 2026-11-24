import {describe, expect, it} from "vitest";
import {
    absorbText, activeCount, activePills, applyFilters, bestRelaxation, datePresets, EMPTY_FILTERS, facetCounts,
    filtersFromSearch, filtersToSearch, summarize, toggleValue, tradeDay,
} from "../src/Transactions/filterModel.js";

const t = (id, symbol, action, asset_type, account_type, created_at, price, quantity) =>
    ({id, symbol, action, asset_type, account_type, created_at, price_of_one: price, quantity});

const TRADES = [
    t(1, "AAPL", "BUY", "stock", "TFSA", "2026-03-10T15:00:00", 100, 5),
    t(2, "AAPL", "SELL", "stock", "TFSA", "2026-05-02T15:00:00", 120, 2),
    t(3, "BTC", "BUY", "crypto", null, "2026-06-20T15:00:00", 50000, 0.01),
    t(4, "SHOP.TO", "BUY", "stock", "RRSP", "2025-12-01T15:00:00", 90, 10),
];
const f = (patch) => ({...EMPTY_FILTERS, ...patch});

describe("applyFilters", () => {
    it("returns everything with no filters", () => expect(applyFilters(TRADES, EMPTY_FILTERS)).toHaveLength(4));
    it("ORs inside a group and ANDs across groups", () => {
        expect(applyFilters(TRADES, f({accounts: ["TFSA", "RRSP"]})).map((x) => x.id)).toEqual([1, 2, 4]);
        expect(applyFilters(TRADES, f({accounts: ["TFSA", "RRSP"], actions: ["BUY"]})).map((x) => x.id)).toEqual([1, 4]);
    });
    it("treats a missing account as UNSET", () => {
        expect(applyFilters(TRADES, f({accounts: ["UNSET"]})).map((x) => x.id)).toEqual([3]);
    });
    it("matches the symbol text case-insensitively", () => {
        expect(applyFilters(TRADES, f({q: "shop"})).map((x) => x.id)).toEqual([4]);
    });
    it("filters by date range and amount", () => {
        expect(applyFilters(TRADES, f({from: "2026-01-01", to: "2026-05-31"})).map((x) => x.id)).toEqual([1, 2]);
        expect(applyFilters(TRADES, f({min: "500"})).map((x) => x.id)).toEqual([1, 3, 4]);
        expect(applyFilters(TRADES, f({max: "300"})).map((x) => x.id)).toEqual([2]);
    });
});

describe("facetCounts", () => {
    it("counts a chip against the OTHER groups only", () => {
        const counts = facetCounts(TRADES, f({actions: ["BUY"], accounts: ["TFSA"]}));
        expect(counts.actions).toEqual({BUY: 1, SELL: 1}); // account TFSA applies, the action group doesn't
        expect(counts.accounts.RRSP).toBe(1); // buys in RRSP
    });
});

describe("summarize", () => {
    it("adds up bought and sold", () => {
        expect(summarize(TRADES)).toEqual({count: 4, bought: 500 + 500 + 900, sold: 240});
    });
});

describe("absorbText", () => {
    it("turns known words into filters and keeps the rest", () => {
        const {filters, rest} = absorbText(EMPTY_FILTERS, "aapl buy tfsa >500 2026");
        expect(filters.actions).toEqual(["BUY"]);
        expect(filters.accounts).toEqual(["TFSA"]);
        expect(filters.min).toBe("500");
        expect(filters.from).toBe("2026-01-01");
        expect(rest).toBe("aapl");
    });
    it("reads 'last 30d'", () => {
        const now = new Date(2026, 5, 30);
        const {filters, rest} = absorbText(EMPTY_FILTERS, "last 30d", now);
        expect(filters.from).toBe("2026-06-01");
        expect(filters.to).toBe("2026-06-30");
        expect(rest).toBe("");
    });
    it("does not duplicate a value", () => {
        expect(absorbText(f({actions: ["BUY"]}), "buy").filters.actions).toEqual(["BUY"]);
    });
});

describe("address round trip", () => {
    it("survives serialize -> parse", () => {
        const filters = f({q: "aapl", actions: ["BUY"], kinds: ["stock"], accounts: ["TFSA", "UNSET"], from: "2026-01-01", min: "10"});
        const back = filtersFromSearch(filtersToSearch(filters, "amount"), ["TFSA"]);
        expect(back.filters).toEqual(filters);
        expect(back.sort).toBe("amount");
    });
    it("drops junk from an edited address", () => {
        const {filters} = filtersFromSearch("action=HACK,BUY&kind=<b>&acct=NOPE&from=tomorrow&min=-5", ["TFSA"]);
        expect(filters).toEqual(f({actions: ["BUY"]}));
    });
});

describe("pills and helpers", () => {
    const label = (g, v) => v;
    it("lists each active filter and removes it", () => {
        const filters = f({actions: ["BUY"], from: "2026-01-01"});
        const pills = activePills(filters, label);
        expect(pills.map((p) => p.key)).toEqual(["actions:BUY", "dates"]);
        expect(pills[0].off(filters).actions).toEqual([]);
        expect(activeCount(filters)).toBe(2);
    });
    it("suggests the filter whose removal helps most", () => {
        const filters = f({actions: ["SELL"], kinds: ["crypto"]}); // nothing is a crypto sell
        const best = bestRelaxation(TRADES, filters, label);
        expect(applyFilters(TRADES, filters)).toHaveLength(0);
        expect(best.count).toBe(1); // dropping "crypto" leaves the AAPL sell
        expect(["actions:SELL", "kinds:crypto"]).toContain(best.pill.key); // a tie: either brings back one trade
    });
    it("toggles a value", () => {
        expect(toggleValue(EMPTY_FILTERS, "actions", "BUY").actions).toEqual(["BUY"]);
        expect(toggleValue(f({actions: ["BUY"]}), "actions", "BUY").actions).toEqual([]);
    });
    it("builds the date presets", () => {
        const [d30, ytd, ly] = datePresets(new Date(2026, 5, 30));
        expect(d30.from).toBe("2026-06-01");
        expect(ytd).toMatchObject({from: "2026-01-01", to: "2026-12-31"});
        expect(ly).toMatchObject({from: "2025-01-01", to: "2025-12-31"});
    });
    it("reads a naive timestamp as UTC", () => {
        expect(tradeDay({created_at: "2026-03-10T15:00:00"})).toMatch(/^2026-03-1[01]$/);
        expect(tradeDay({created_at: "nonsense"})).toBe("");
    });
});
