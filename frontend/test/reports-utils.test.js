import {describe, expect, it} from "vitest";
import {
    cad,
    inclusionLine,
    pickYear,
    plural,
    saleDates,
    saleFlags,
    securityLabel,
    signedCad,
    superficialLossesNote,
    warningCounts,
} from "../src/Reports/reportUtils.js";
import {formatMoney} from "../src/utils/format.js";

describe("capital gains report helpers", () => {
    it("formats every amount in CAD", () => {
        expect(cad(1234.5)).toBe(formatMoney(1234.5, "CAD"));
        expect(signedCad(-10)).toBe(`−${formatMoney(10, "CAD")}`);
        expect(signedCad(10)).toBe(`+${formatMoney(10, "CAD")}`);
    });

    it("picks the asked year when it has sales, else the newest", () => {
        expect(pickYear([2025, 2023], 2023)).toBe(2023);
        expect(pickYear([2025, 2023], "2023")).toBe(2023);
        expect(pickYear([2025, 2023], 2024)).toBe(2025);
        expect(pickYear([2025, 2023], null)).toBe(2025);
        expect(pickYear([], 2024)).toBeNull();
        expect(pickYear(undefined, 2024)).toBeNull();
    });

    it("labels the warnings of a sale, most important first", () => {
        expect(saleFlags({})).toEqual([]);
        expect(saleFlags({oversold: true, superficial_loss: true, foreign_currency: true}).map((f) => f.kind))
            .toEqual(["oversold", "superficial", "foreign"]);
        expect(saleFlags({superficial_loss: true})[0].label).toBe("Possible superficial loss");
        expect(saleFlags({foreign_currency: true, interlisted: true, acb_may_rise: true}).map((f) => f.kind))
            .toEqual(["acb", "interlisted", "foreign"]);
    });

    it("counts warnings across sales", () => {
        expect(warningCounts([{oversold: true}, {superficial_loss: true, foreign_currency: true},
            {foreign_currency: true}, {interlisted: true}])).toEqual(
            {oversold: 1, superficial: 1, acb: 0, interlisted: 1, foreign: 2});
        expect(warningCounts(undefined)).toEqual({oversold: 0, superficial: 0, acb: 0, interlisted: 0, foreign: 0});
    });

    it("notes how much of the losses may be superficial", () => {
        expect(superficialLossesNote({possibly_superficial: 0})).toBeNull();
        expect(superficialLossesNote(undefined)).toBeNull();
        expect(superficialLossesNote({possibly_superficial: 80})).toBe(
            `Includes up to ${cad(80)} of possibly superficial losses, which CRA may deny (see the flagged sales).`);
    });

    it("shows the settlement date when it differs from the trade date", () => {
        expect(saleDates({date: "2024-12-31", settlement_date: "2025-01-02"}))
            .toBe("2024-12-31 (settles 2025-01-02)");
        expect(saleDates({date: "2024-12-31", settlement_date: "2024-12-31"})).toBe("2024-12-31");
        expect(saleDates({date: "2024-12-31"})).toBe("2024-12-31");
    });

    it("explains the inclusion rate only for a net gain", () => {
        expect(inclusionLine({net: 1000, taxable_at_50pct: 500}))
            .toBe(`50% of a net capital gain is taxable: ${cad(500)} of ${cad(1000)}.`);
        expect(inclusionLine({net: -5, taxable_at_50pct: 0})).toMatch(/net capital loss isn't taxable/);
        expect(inclusionLine({net: 0, taxable_at_50pct: 0})).toBe("No net capital gain this year.");
    });

    it("names the security and its type", () => {
        expect(securityLabel({symbol: "BTC", asset_type: "crypto"})).toBe("BTC · Crypto");
        expect(securityLabel({symbol: "AAPL", asset_type: "stock"})).toBe("AAPL · Stock");
    });

    it("pluralizes", () => {
        expect(plural(1, "sale")).toBe("1 sale");
        expect(plural(2, "sale")).toBe("2 sales");
        expect(plural(2, "loss", "losses")).toBe("2 losses");
    });
});
