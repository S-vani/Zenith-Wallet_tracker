import {describe, expect, it} from "vitest";
import {backdatedPriceHint, fullMoney, fullPrice, fullSignedMoney} from "../src/Transactions/tradeForm.js";

// test/setup.js pins the locale to en-US and the time zone to America/Toronto

describe("backdatedPriceHint", () => {
    const initialDate = "2024-06-15T14:30";
    const prefilled = "187.5";
    const form = (changes) => ({action: "BUY", price_of_one: prefilled, created_at: initialDate, ...changes});

    it("says nothing while the date is today", () => {
        expect(backdatedPriceHint(form(), initialDate, prefilled)).toBeNull();
        // an earlier time on the same day: the current price is still a fair starting point
        expect(backdatedPriceHint(form({created_at: "2024-06-15T09:00"}), initialDate, prefilled)).toBeNull();
    });

    it("flags the untouched current price on another day", () => {
        expect(backdatedPriceHint(form({created_at: "2023-01-10T10:00"}), initialDate, prefilled))
            .toBe("This is the current price — enter what you paid on Jan 10, 2023.");
        expect(backdatedPriceHint(form({action: "SELL", created_at: "2023-01-10T10:00"}), initialDate, prefilled))
            .toBe("This is the current price — enter what you sold for on Jan 10, 2023.");
    });

    it("goes away once the price is changed", () => {
        expect(backdatedPriceHint(form({created_at: "2023-01-10T10:00", price_of_one: "150"}), initialDate, prefilled))
            .toBeNull();
    });

    it("needs a prefilled price and a valid date", () => {
        expect(backdatedPriceHint(form({created_at: "2023-01-10T10:00", price_of_one: ""}), initialDate, ""))
            .toBeNull();
        expect(backdatedPriceHint(form({created_at: ""}), initialDate, prefilled)).toBeNull();
        expect(backdatedPriceHint(form({created_at: "2023-99-99Tzz"}), initialDate, prefilled)).toBeNull();
    });
});

describe("full amounts in the trade details", () => {
    it("never shortens huge amounts", () => {
        expect(fullMoney(97.5e12, "CAD")).toBe("CA$97,500,000,000,000.00");
        expect(fullMoney(1234.5, "USD")).toBe("US$1,234.50");
        expect(fullMoney(5, null)).toBe("—");
    });

    it("keeps small prices readable and huge ones exact", () => {
        expect(fullPrice(0.0006481, "CAD")).toBe("CA$0.0006481");
        expect(fullPrice(2e12, "CAD")).toBe("CA$2,000,000,000,000.00");
    });

    it("signs profits with a real minus", () => {
        expect(fullSignedMoney(3e12, "CAD")).toBe("+CA$3,000,000,000,000.00");
        expect(fullSignedMoney(-12.5, "CAD")).toBe("−CA$12.50");
        expect(fullSignedMoney(0.001, "CAD")).toBe("CA$0.00");
        expect(fullSignedMoney(-12, null)).toBe("—");
    });
});
