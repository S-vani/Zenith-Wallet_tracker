import {describe, expect, it} from "vitest";
import {formatPrice, priceInputValue} from "../src/utils/format.js";

// test/setup.js pins the locale to en-US, so CAD shows as "CA$"

describe("formatPrice", () => {
    it("uses 2 decimals for normal prices", () => {
        expect(formatPrice(1234.5, "CAD")).toBe("CA$1,234.50");
        expect(formatPrice(3, "USD")).toBe("$3.00");
    });

    it("keeps meaningful digits for sub-dollar coins", () => {
        expect(formatPrice(0.1234, "USD")).toBe("$0.1234");
        expect(formatPrice(0.000648, "USD")).toBe("$0.000648");
    });

    it("never shows a real sub-cent price as $0.00", () => {
        expect(formatPrice(5.43793e-10, "USD")).toBe("$0.0000000005438");
        expect(formatPrice(4.3354e-8, "USD")).toBe("$0.00000004335");
        expect(formatPrice(5.43793e-10, "USD")).not.toBe("$0.00");
    });

    it("handles zero and bad input", () => {
        expect(formatPrice(0, "USD")).toBe("$0.00");
        expect(formatPrice(undefined, "USD")).toBe("$0.00");
    });
});

describe("priceInputValue", () => {
    it("gives plain strings for the price input", () => {
        expect(priceInputValue(119176)).toBe("119176");
        expect(priceInputValue(770.689)).toBe("770.69");
        expect(priceInputValue(0.000648)).toBe("0.000648");
    });

    it("never uses exponent notation or rounds tiny prices to 0", () => {
        expect(priceInputValue(5.43793e-10)).toBe("0.0000000005438");
        expect(priceInputValue(5.43793e-10)).not.toMatch(/e/);
    });

    it("returns an empty string when there's no usable price", () => {
        expect(priceInputValue(0)).toBe("");
        expect(priceInputValue(undefined)).toBe("");
        expect(priceInputValue(-3)).toBe("");
    });
});
