import {describe, expect, it} from "vitest";
import {
    changeClass,
    formatMoney,
    formatPercent,
    formatPrice,
    formatQuantity,
    formatSignedMoney,
    listingName,
    normalizeCurrency,
    SUPPORTED_CURRENCIES,
} from "../src/utils/format.js";

// test/setup.js pins the locale to en-US

describe("normalizeCurrency", () => {
    it("keeps supported currencies", () => {
        for (const code of SUPPORTED_CURRENCIES) expect(normalizeCurrency(code)).toBe(code);
    });

    it("uppercases and trims", () => {
        expect(normalizeCurrency("usd")).toBe("USD");
        expect(normalizeCurrency("  eur ")).toBe("EUR");
    });

    it.each(["", "   ", null, undefined, "GBP", "dollars", 42])("falls back to CAD for %j", (value) => {
        expect(normalizeCurrency(value)).toBe("CAD");
    });
});

describe("formatMoney", () => {
    it("formats each supported currency with 2 decimals", () => {
        expect(formatMoney(1234.5, "CAD")).toBe("CA$1,234.50");
        expect(formatMoney(1234.5, "USD")).toBe("US$1,234.50");
        expect(formatMoney(1234.5, "EUR")).toBe("€1,234.50");
    });

    // regression: a USD account saw a bare "$", which Canadians read as their own dollar
    it("spells USD as US$ while CAD keeps its usual symbol", () => {
        expect(formatMoney(5, "USD")).toBe("US$5.00");
        expect(formatMoney(-5, "USD")).toBe("-US$5.00");
        expect(formatMoney(5, "CAD")).toBe("CA$5.00");
        expect(formatMoney(5, "USD")).not.toMatch(/US\$.*US\$/); // never doubled
    });

    it("defaults to CAD", () => {
        expect(formatMoney(5)).toBe("CA$5.00");
    });

    it.each(["", "usd", "GBP", null, undefined])("does not throw for currency %j", (currency) => {
        expect(() => formatMoney(10, currency)).not.toThrow();
    });

    it("shows a dash, not a guessed CA$, while the user's currency isn't known (null)", () => {
        expect(formatMoney(1234.5, null)).toBe("—");
        expect(formatPrice(0.0006, null)).toBe("—");
        expect(formatSignedMoney(-12, null)).toBe("—");
        expect(formatSignedMoney(12, null)).toBe("—");
    });

    it("normalizes lowercase, empty and unknown currencies", () => {
        expect(formatMoney(10, "usd")).toBe("US$10.00");
        expect(formatMoney(10, "")).toBe("CA$10.00");
        expect(formatMoney(10, "GBP")).toBe("CA$10.00");
    });

    it("rounds to cents", () => {
        expect(formatMoney(1.234, "USD")).toBe("US$1.23");
        expect(formatMoney(1.236, "USD")).toBe("US$1.24");
    });

    it("treats non-numbers as zero", () => {
        expect(formatMoney(undefined, "USD")).toBe("US$0.00");
        expect(formatMoney(null, "USD")).toBe("US$0.00");
        expect(formatMoney("abc", "USD")).toBe("US$0.00");
        expect(formatMoney(NaN, "USD")).toBe("US$0.00");
        expect(formatMoney("12.5", "USD")).toBe("US$12.50");
    });

    it("never shows a minus sign on an amount that rounds to zero", () => {
        expect(formatMoney(-0.001, "CAD")).toBe("CA$0.00");
        expect(formatMoney(-0.004, "USD")).toBe("US$0.00");
        expect(formatMoney(-0.005, "CAD")).toBe("-CA$0.01");
    });

    it("formats negatives", () => {
        expect(formatMoney(-3, "EUR")).toBe("-€3.00");
    });

    it("keeps normal notation just below a trillion", () => {
        expect(formatMoney(999_999_999_999, "USD")).toBe("US$999,999,999,999.00");
    });

    it("switches to compact notation for huge numbers", () => {
        expect(formatMoney(1e12, "USD")).toBe("US$1T");
        expect(formatMoney(1.5e12, "CAD")).toBe("CA$1.5T");
        expect(formatMoney(-2.5e12, "USD")).toBe("-US$2.5T");
        expect(formatMoney(1e30, "USD").length).toBeLessThan(40);
    });

    it("honours explicit options", () => {
        expect(formatMoney(1.23456, "USD", {maximumFractionDigits: 4})).toBe("US$1.2346");
    });
});

describe("formatSignedMoney", () => {
    it("adds a sign for gains and losses", () => {
        expect(formatSignedMoney(12.3, "USD")).toBe("+US$12.30");
        expect(formatSignedMoney(-12.3, "USD")).toBe("−US$12.30");
    });

    it.each([0, 0.004, -0.004, -0.0049, 1e-12, -1e-12])("shows %d as an unsigned zero", (value) => {
        expect(formatSignedMoney(value, "USD")).toBe("US$0.00");
    });

    it("never shows a negative zero", () => {
        for (const value of [-0, -0.001, -0.0049999]) {
            expect(formatSignedMoney(value, "CAD")).not.toMatch(/[−-]/);
        }
    });

    it("signs the smallest visible amounts", () => {
        expect(formatSignedMoney(0.006, "USD")).toBe("+US$0.01");
        expect(formatSignedMoney(-0.006, "USD")).toBe("−US$0.01");
    });

    it("handles invalid input and huge values", () => {
        expect(formatSignedMoney(undefined, "USD")).toBe("US$0.00");
        expect(formatSignedMoney(-3e12, "USD")).toBe("−US$3T");
    });
});

describe("formatPercent", () => {
    it("formats with a sign and 2 decimals", () => {
        expect(formatPercent(1.234)).toBe("+1.23%");
        expect(formatPercent(-1.5)).toBe("−1.50%");
        expect(formatPercent("2.5")).toBe("+2.50%");
    });

    it.each([0, 0.004, -0.004, -0])("shows %d as 0.00%", (value) => {
        expect(formatPercent(value)).toBe("0.00%");
    });

    it.each([NaN, Infinity, -Infinity, "abc", undefined])("shows a dash for %j", (value) => {
        expect(formatPercent(value)).toBe("—");
    });

    it("treats null as zero", () => {
        expect(formatPercent(null)).toBe("0.00%");
    });
});

describe("formatQuantity", () => {
    it("removes float noise", () => {
        expect(formatQuantity(0.1 + 0.2)).toBe("0.3");
        expect(formatQuantity(0.3 - 0.1)).toBe("0.2");
    });

    it("shows up to 8 decimals", () => {
        expect(formatQuantity(0.00000001)).toBe("0.00000001");
        expect(formatQuantity(1.123456789)).toBe("1.12345679");
    });

    it("groups thousands and drops trailing zeros", () => {
        expect(formatQuantity(1234567)).toBe("1,234,567");
        expect(formatQuantity(2.5)).toBe("2.5");
        expect(formatQuantity("3.10")).toBe("3.1");
    });

    it("uses compact notation for huge quantities", () => {
        expect(formatQuantity(2e12)).toBe("2T");
        expect(formatQuantity(1e30).length).toBeLessThan(40);
    });
});

describe("changeClass", () => {
    it.each([
        [1, "positive"],
        [0.0001, "positive"],
        ["5", "positive"],
        [-1, "negative"],
        ["-0.5", "negative"],
        [0, "neutral"],
        [NaN, "neutral"],
        [undefined, "neutral"],
        ["abc", "neutral"],
    ])("%j -> %s", (value, expected) => {
        expect(changeClass(value)).toBe(expected);
    });
});

describe("listingName", () => {
    it("puts the exchange before a stock's name so SHOP and SHOP.TO can be told apart", () => {
        expect(listingName({type: "stock", symbol: "SHOP.TO", name: "Shopify Inc.", exchange: "TSX"}))
            .toBe("TSX · Shopify Inc.");
        expect(listingName({type: "stock", symbol: "SHOP", name: "Shopify Inc.", exchange: "NYSE"}))
            .toBe("NYSE · Shopify Inc.");
    });

    it("copes with missing parts and leaves coins alone", () => {
        expect(listingName({type: "stock", name: "Apple Inc."})).toBe("Apple Inc.");
        expect(listingName({type: "stock", exchange: "TSX", name: ""})).toBe("TSX");
        expect(listingName({type: "crypto", name: "Bitcoin", exchange: "x"})).toBe("Bitcoin");
        expect(listingName(null)).toBe("");
    });
});
