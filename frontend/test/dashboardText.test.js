import {describe, expect, it} from "vitest";
import {dashboardChartSummary, unpricedNote} from "../src/Dashboard/dashboardText.js";

// test/setup.js pins the locale to en-US, where CAD shows as "CA$"
const normalize = (s) => s.replace(/\s/g, " ");

describe("unpricedNote", () => {
    it("says nothing when every holding has a price", () => {
        expect(unpricedNote([])).toBeNull();
        expect(unpricedNote(undefined)).toBeNull();
        expect(unpricedNote(null)).toBeNull();
    });

    it("names one holding", () => {
        expect(unpricedNote(["pepe"])).toBe("PEPE has no price right now and isn't included in the totals.");
    });

    it("names two or three holdings", () => {
        expect(unpricedNote(["pepe", "GONE"]))
            .toBe("PEPE and GONE have no price right now and aren't included in the totals.");
        expect(unpricedNote(["a", "b", "c"]))
            .toBe("A, B and C have no price right now and aren't included in the totals.");
    });

    it("counts the rest of a long list", () => {
        expect(unpricedNote(["a", "b", "c", "d"])).toBe(
            "A, B, C and 1 other have no price right now and aren't included in the totals.");
        expect(unpricedNote(["a", "b", "c", "d", "e"])).toBe(
            "A, B, C and 2 others have no price right now and aren't included in the totals.");
    });

    it("ignores duplicates and blanks", () => {
        expect(unpricedNote(["pepe", "PEPE", ""])).toBe(
            "PEPE has no price right now and isn't included in the totals.");
    });
});

describe("dashboardChartSummary", () => {
    const chart = [
        {time: "2025-10-01T00:00:00Z", value: 12000, invested: 10000},
        {time: "2026-03-01T00:00:00Z", value: 11500, invested: 10000},
        {time: "2026-08-01T00:00:00Z", value: 56000, invested: 40000},
        {time: "2026-10-01T00:00:00Z", value: 53900, invested: 40000},
    ];

    it("reads out the value line, then the invested line", () => {
        expect(normalize(dashboardChartSummary(chart, "year", "CAD"))).toBe(
            "Portfolio value over the past year: from CA$12,000.00 to CA$53,900.00, high CA$56,000.00, " +
            "low CA$11,500.00. Amount invested in what you hold: from CA$10,000.00 to CA$40,000.00, " +
            "high CA$40,000.00, low CA$10,000.00.");
    });

    it("words every range", () => {
        expect(dashboardChartSummary(chart, "day", "CAD")).toMatch(/^Portfolio value over the past day: /);
        expect(dashboardChartSummary(chart, "week", "CAD")).toMatch(/^Portfolio value over the past week: /);
        expect(dashboardChartSummary(chart, "month", "CAD")).toMatch(/^Portfolio value over the past month: /);
        expect(dashboardChartSummary(chart, "all", "CAD")).toMatch(/^Portfolio value since you joined: /);
    });

    it("leaves the invested part out for charts saved before it existed", () => {
        const old = chart.map(({time, value}) => ({time, value}));
        expect(dashboardChartSummary(old, "year", "USD")).not.toContain("invested");
        expect(normalize(dashboardChartSummary(old, "year", "USD"))).toContain("from $12,000.00 to $53,900.00");
    });

    it("handles no data", () => {
        expect(dashboardChartSummary([], "week", "CAD")).toBe("Portfolio value over the past week: no data.");
    });
});
