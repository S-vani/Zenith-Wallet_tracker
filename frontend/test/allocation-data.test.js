import {describe, expect, it} from "vitest";
import {
    ALLOCATION_COLORS, OTHER_COLOR, OTHER_KEY, allocationRows, allocationSummary, availableViews, formatWeight,
    groupTopN, sliceLabel,
} from "../src/Dashboard/allocationData.js";

// test/setup.js pins the locale to en-US, where CAD shows as "CA$"
const normalize = (s) => s.replace(/\s/g, " ");

const holding = (symbol, value, total, asset_type = "stock") => ({symbol, asset_type, value, weight: value / total});

const REPLY = {
    currency: "CAD",
    total: 1000,
    unpriced: [],
    by_asset_type: [{key: "stock", value: 600, weight: 0.6}, {key: "crypto", value: 400, weight: 0.4}],
    by_account: [{key: "TFSA", value: 500, weight: 0.5}, {key: "UNSET", value: 300, weight: 0.3},
        {key: "NON_REGISTERED", value: 200, weight: 0.2}],
    by_holding: [holding("btc", 400, 1000, "crypto"), holding("AAPL", 600, 1000)],
    by_currency: [{key: "USD", value: 600, weight: 0.6}, {key: "CRYPTO", value: 400, weight: 0.4}],
};

describe("groupTopN", () => {
    const rows = Array.from({length: 11}, (_, i) => ({key: `S${i}`, label: `S${i}`, value: 11 - i, weight: (11 - i) / 66}));

    it("keeps short lists as they are", () => {
        expect(groupTopN(rows.slice(0, 8))).toEqual(rows.slice(0, 8));
        expect(groupTopN([])).toEqual([]);
        expect(groupTopN(undefined)).toEqual([]);
    });

    it("adds up everything after the top 8 into one Other row", () => {
        const grouped = groupTopN(rows);
        expect(grouped).toHaveLength(9);
        expect(grouped.slice(0, 8)).toEqual(rows.slice(0, 8));
        const other = grouped[8];
        expect(other.key).toBe(OTHER_KEY);
        expect(other.label).toBe("Other (3)");
        expect(other.value).toBe(3 + 2 + 1);
        expect(other.weight).toBeCloseTo(6 / 66);
        // nothing is lost: the shares still add up to the whole
        expect(grouped.reduce((sum, r) => sum + r.weight, 0)).toBeCloseTo(1);
    });

    it("takes a custom size", () => {
        expect(groupTopN(rows, 2).map((r) => r.key)).toEqual(["S0", "S1", OTHER_KEY]);
    });
});

describe("formatWeight", () => {
    it("shows a share with one decimal", () => {
        expect(formatWeight(0.4567)).toBe("45.7%");
        expect(formatWeight(1)).toBe("100.0%");
        expect(formatWeight(0)).toBe("0.0%");
    });

    it("never shows a real sliver as nothing", () => {
        expect(formatWeight(0.0001)).toBe("<0.1%");
    });

    it("shows a dash for a missing share", () => {
        expect(formatWeight(null)).toBe("—");
        expect(formatWeight(undefined)).toBe("—");
        expect(formatWeight("x")).toBe("—");
    });
});

describe("sliceLabel", () => {
    it("names each group in words", () => {
        expect(sliceLabel("asset_type", "stock")).toBe("Stocks");
        expect(sliceLabel("asset_type", "crypto")).toBe("Crypto");
        expect(sliceLabel("account", "UNSET")).toBe("Not set");
        expect(sliceLabel("account", "NON_REGISTERED")).toBe("Non-registered");
        expect(sliceLabel("account", "TFSA")).toBe("TFSA");
        expect(sliceLabel("holding", "btc")).toBe("BTC");
        expect(sliceLabel("currency", "CRYPTO")).toBe("Crypto");
        expect(sliceLabel("currency", "USD")).toBe("USD");
    });
});

describe("availableViews", () => {
    it("offers a tab for each group the server sent", () => {
        expect(availableViews(REPLY).map((v) => v.value)).toEqual(["asset_type", "account", "holding", "currency"]);
        const older = {...REPLY, by_currency: undefined};
        expect(availableViews(older).map((v) => v.value)).toEqual(["asset_type", "account", "holding"]);
        expect(availableViews(undefined)).toEqual([]);
    });
});

describe("allocationRows", () => {
    it("labels and colours each row, largest first as sent", () => {
        const rows = allocationRows(REPLY, "account");
        expect(rows.map((r) => r.label)).toEqual(["TFSA", "Not set", "Non-registered"]);
        expect(rows.map((r) => r.color)).toEqual(ALLOCATION_COLORS.slice(0, 3));
        expect(new Set(rows.map((r) => r.key)).size).toBe(3);
    });

    it("keys holdings by type and symbol and shows tickers in capitals", () => {
        const rows = allocationRows(REPLY, "holding");
        expect(rows.map((r) => [r.key, r.label])).toEqual([["crypto:btc", "BTC"], ["stock:AAPL", "AAPL"]]);
    });

    it("caps the slices at 8 distinct colours plus a grey Other", () => {
        const many = Array.from({length: 12}, (_, i) => holding(`T${i}`, 12 - i, 78));
        const rows = allocationRows({...REPLY, by_holding: many}, "holding");
        expect(rows).toHaveLength(9);
        expect(new Set(rows.slice(0, 8).map((r) => r.color)).size).toBe(8);
        expect(rows[8].color).toBe(OTHER_COLOR);
        expect(rows[8].label).toBe("Other (4)");
    });

    it("copes with a missing group or empty values", () => {
        expect(allocationRows({}, "account")).toEqual([]);
        expect(allocationRows(REPLY, "nonsense")).toEqual([]);
        expect(allocationRows({by_account: [{key: "TFSA", value: 0, weight: 0}]}, "account")).toEqual([]);
    });
});

describe("allocationSummary", () => {
    it("reads out each slice with its share and amount", () => {
        const rows = allocationRows(REPLY, "account");
        expect(normalize(allocationSummary(rows, "account", "CAD"))).toBe(
            "Allocation by account: TFSA 50.0% (CA$500.00), Not set 30.0% (CA$300.00), " +
            "Non-registered 20.0% (CA$200.00).");
    });

    it("uses the view's own wording", () => {
        const rows = allocationRows(REPLY, "currency");
        expect(normalize(allocationSummary(rows, "currency", "USD")))
            .toBe("Allocation by listing currency: USD 60.0% (US$600.00), Crypto 40.0% (US$400.00).");
    });

    it("says when there is nothing to split up", () => {
        expect(allocationSummary([], "holding", "CAD")).toBe("Allocation by holding: no priced holdings.");
    });

    it("shows a dash for amounts while the currency is unknown", () => {
        const rows = allocationRows(REPLY, "asset_type");
        expect(allocationSummary(rows, "asset_type", null))
            .toBe("Allocation by asset type: Stocks 60.0% (—), Crypto 40.0% (—).");
    });
});
