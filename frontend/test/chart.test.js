import {describe, expect, it} from "vitest";
import {dailyTicks, tooltipDate} from "../src/utils/chart.js";

// test/setup.js pins the time zone to America/Toronto and the locale to en-US
const normalize = (s) => s.replace(/\s/g, " ");

function hourly(startIso, hours, key = "time") {
    const start = new Date(startIso).getTime();
    return Array.from({length: hours}, (_, i) => ({[key]: new Date(start + i * 3600_000).toISOString(), value: i}));
}

describe("dailyTicks", () => {
    it("returns nothing for no data", () => {
        expect(dailyTicks([])).toEqual([]);
    });

    it("puts one tick at the first point of each local day", () => {
        // 3 days of hourly data starting at local midnight (04:00 UTC during daylight saving time)
        const ticks = dailyTicks(hourly("2024-06-03T04:00:00Z", 72));

        expect(ticks).toEqual([
            "2024-06-03T04:00:00.000Z",
            "2024-06-04T04:00:00.000Z",
            "2024-06-05T04:00:00.000Z",
        ]);
    });

    it("uses local, not UTC, day boundaries", () => {
        // 00:00 UTC June 4 is still June 3 in Toronto, so the next tick is at local midnight (04:00 UTC)
        const data = hourly("2024-06-04T00:00:00Z", 24);
        expect(dailyTicks(data)).toEqual(["2024-06-04T00:00:00.000Z", "2024-06-04T04:00:00.000Z"]);
    });

    it("gives a single tick for one day of data", () => {
        expect(dailyTicks(hourly("2024-06-03T05:00:00Z", 10))).toHaveLength(1);
    });

    it("gives a tick per day for a week of hourly data", () => {
        const ticks = dailyTicks(hourly("2024-06-03T04:00:00Z", 24 * 7));
        expect(ticks).toHaveLength(7);
        expect(new Set(ticks.map((t) => new Date(t).toDateString())).size).toBe(7);
    });

    it("supports a custom key and numeric timestamps", () => {
        const data = [
            {date: Date.UTC(2024, 0, 1, 15)},
            {date: Date.UTC(2024, 0, 1, 16)},
            {date: Date.UTC(2024, 0, 2, 15)},
        ];
        expect(dailyTicks(data, "date")).toEqual([Date.UTC(2024, 0, 1, 15), Date.UTC(2024, 0, 2, 15)]);
    });
});

describe("tooltipDate", () => {
    const value = "2024-06-03T18:05:00Z"; // 2:05 PM in Toronto

    it("shows the time for intraday ranges", () => {
        expect(normalize(tooltipDate(value, true))).toBe("Jun 3, 2:05 PM");
    });

    it("shows only the date for longer ranges", () => {
        expect(normalize(tooltipDate(value, false))).toBe("Jun 3, 2024");
    });

    it("accepts timestamps", () => {
        expect(normalize(tooltipDate(Date.parse(value), false))).toBe("Jun 3, 2024");
    });
});
