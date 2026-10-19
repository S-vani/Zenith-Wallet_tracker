import {beforeEach, describe, expect, it} from "vitest";
import {
    CACHE_MS, clearDashboardCache, readDashboardCache, writeDashboardCache,
} from "../src/Dashboard/dashboardCache.js";

describe("dashboard range cache", () => {
    beforeEach(() => clearDashboardCache());

    const entry = {range: "week", days: 7, stats: {value: 10, curr_timeperiod: 1}, chart: []};

    it("returns a saved range for a minute", () => {
        writeDashboardCache("k", entry, 1000);
        expect(readDashboardCache("k", 1000)).toBe(entry);
        expect(readDashboardCache("k", 1000 + CACHE_MS - 1)).toBe(entry);
    });

    it("keeps each range's chart with its invested amounts", () => {
        const week = {...entry, chart: [{time: "t1", value: 120, invested: 100}]};
        const year = {range: "year", days: 365, stats: entry.stats, chart: [{time: "t0", value: 90, invested: 80}]};
        writeDashboardCache("week", week, 0);
        writeDashboardCache("year", year, 0);
        expect(readDashboardCache("week", 1).chart[0].invested).toBe(100);
        expect(readDashboardCache("year", 1).chart[0].invested).toBe(80);
    });

    it("forgets it after a minute", () => {
        writeDashboardCache("k", entry, 1000);
        expect(readDashboardCache("k", 1000 + CACHE_MS)).toBeUndefined();
    });

    it("keeps ranges apart and ignores missing keys", () => {
        writeDashboardCache("a", entry, 0);
        expect(readDashboardCache("b", 0)).toBeUndefined();
        expect(readDashboardCache(null, 0)).toBeUndefined();
    });

    it("drops expired entries when saving", () => {
        writeDashboardCache("old", entry, 0);
        writeDashboardCache("new", entry, CACHE_MS * 2);
        expect(readDashboardCache("old", 0)).toBeUndefined(); // gone, not just too old
    });
});
