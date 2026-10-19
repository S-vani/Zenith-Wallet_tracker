import {describe, expect, it} from "vitest";
import {
    MONTHS, RANGE_PHRASES, axisMoneyOptions, axisTicks, chartSummary, dailyTicks, formatAxisTick, priceChartSummary,
    tickUnit, tooltipDate,
} from "../src/utils/chart.js";
import {formatMoney} from "../src/utils/format.js";

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

    it("always abbreviates September as Sep", () => {
        expect(normalize(tooltipDate("2025-09-20T16:00:00Z", false))).toBe("Sep 20, 2025");
    });
});

// one point per local day at noon, starting on a local date
function daily(startDate, days) {
    const [y, m, d] = startDate.split("-").map(Number);
    return Array.from({length: days}, (_, i) => ({time: new Date(y, m - 1, d + i, 12).toISOString(), value: i}));
}

describe("tickUnit", () => {
    it("uses times for a day or less", () => {
        expect(tickUnit(hourly("2024-06-03T04:00:00Z", 24))).toBe("time");
        expect(tickUnit([])).toBe("time");
        expect(tickUnit(undefined)).toBe("time");
    });

    it("uses days for a week to about three months", () => {
        expect(tickUnit(hourly("2024-06-03T04:00:00Z", 24 * 7))).toBe("day");
        expect(tickUnit(daily("2024-06-01", 30))).toBe("day");
        expect(tickUnit(daily("2024-06-01", 90))).toBe("day");
    });

    it("uses months for a year or more", () => {
        expect(tickUnit(daily("2024-01-01", 365))).toBe("month");
        expect(tickUnit(daily("2020-01-01", 5 * 365))).toBe("month");
    });
});

describe("formatAxisTick", () => {
    const value = new Date(2025, 9, 5, 14, 30).toISOString(); // Oct 5, 2025, 2:30 PM local

    it("formats each unit", () => {
        expect(normalize(formatAxisTick(value, "time"))).toBe("2:30 PM");
        expect(formatAxisTick(value, "day")).toBe("Oct 5");
        expect(formatAxisTick(value, "month")).toBe("Oct ’25"); // not "Oct 25", which reads like a day
    });

    it("uses the same abbreviation for every month", () => {
        const labels = MONTHS.map((_, m) => formatAxisTick(new Date(2025, m, 1).toISOString(), "month"));
        expect(labels).toEqual(MONTHS.map((name) => `${name} ’25`));
        expect(labels).toContain("Sep ’25");
        expect(labels.join(" ")).not.toContain("Sept");
    });
});

describe("axisTicks", () => {
    const labels = (data, unit) => axisTicks(data, unit).map((t) => formatAxisTick(t, unit));

    it("leaves intraday ticks to recharts", () => {
        expect(axisTicks(hourly("2024-06-03T04:00:00Z", 24), "time")).toBeUndefined();
    });

    it("gives every month one unique, unambiguous label over a long range", () => {
        // regression: an "All" chart used to show "Nov 25, Nov 25" and "Jun 26, Jun 26"
        const data = daily("2025-10-01", 380);
        const shown = labels(data, "month");
        expect(new Set(shown).size).toBe(shown.length);
        expect(shown.length).toBeLessThanOrEqual(8);
        expect(shown[shown.length - 1]).toBe("Oct ’26"); // the newest month is always labelled
        shown.forEach((label) => expect(label).toMatch(/^[A-Z][a-z]{2} ’\d\d$/));
    });

    it("keeps every month when there are few of them", () => {
        expect(labels(daily("2025-01-01", 150), "month")).toEqual(["Jan ’25", "Feb ’25", "Mar ’25", "Apr ’25", "May ’25"]);
    });

    it("drops a short first month that would crowd the next label", () => {
        // joined Oct 28: "Oct ’25" would sit a few pixels from "Nov ’25"
        expect(labels(daily("2025-10-28", 120), "month")[0]).toBe("Nov ’25");
    });

    it("gives unique day labels for a month of data", () => {
        const shown = labels(daily("2024-06-01", 30), "day");
        expect(new Set(shown).size).toBe(shown.length);
        expect(shown.length).toBeLessThanOrEqual(8);
        expect(shown[shown.length - 1]).toBe("Jun 30");
    });

    it("gives one tick per day for a week of hourly data", () => {
        const ticks = axisTicks(hourly("2024-06-03T04:00:00Z", 24 * 7), "day");
        expect(ticks).toHaveLength(7);
        expect(ticks).toEqual(dailyTicks(hourly("2024-06-03T04:00:00Z", 24 * 7)));
    });

    it("handles no data", () => {
        expect(axisTicks([], "day")).toBeUndefined();
    });
});

describe("axisMoneyOptions", () => {
    // tick values like recharts would draw them: 5 evenly spaced values across the range
    const ticks = (low, high) => Array.from({length: 5}, (_, i) => low + (high - low) * i / 4);
    const tickLabels = (low, high) => {
        const options = axisMoneyOptions([low, high]);
        return ticks(low, high).map((v) => formatMoney(v, "CAD", options));
    };

    it("shows enough decimals for a stablecoin's tiny range", () => {
        // regression: every tick read "CA$1.41"
        const shown = tickLabels(1.405, 1.415);
        expect(new Set(shown).size).toBe(5);
        expect(shown[0]).toBe("CA$1.405");
    });

    it("uses whole dollars for wide ranges and cents for narrow ones", () => {
        expect(tickLabels(700, 800)).toEqual(["CA$700", "CA$725", "CA$750", "CA$775", "CA$800"]);
        expect(tickLabels(10, 12)[1]).toBe("CA$10.50");
    });

    it("uses compact labels for big values that move enough", () => {
        const shown = tickLabels(110_000, 126_000);
        expect(shown[0]).toBe("CA$110K");
        expect(new Set(shown).size).toBe(5);
    });

    it("switches to full amounts when compact labels would repeat", () => {
        // a quiet day for BTC: "CA$114k" five times before
        const shown = tickLabels(114_400, 114_600);
        expect(new Set(shown).size).toBe(5);
        expect(shown[0]).toBe("CA$114,400");
    });

    it("keeps tiny coin prices readable", () => {
        const shown = tickLabels(0.0000150, 0.0000160);
        expect(new Set(shown).size).toBe(5);
        shown.forEach((label) => expect(label).not.toBe("CA$0.00"));
    });

    it("copes with flat or missing data", () => {
        expect(formatMoney(5, "CAD", axisMoneyOptions([5, 5]))).toBe("CA$5.00");
        expect(formatMoney(0.0002, "CAD", axisMoneyOptions([0.0002, 0.0002]))).not.toBe("CA$0.00");
        expect(axisMoneyOptions([])).toEqual({minimumFractionDigits: 0, maximumFractionDigits: 0});
        expect(axisMoneyOptions([NaN, undefined])).toEqual({minimumFractionDigits: 0, maximumFractionDigits: 0});
    });

    it("handles a portfolio that starts at zero", () => {
        expect(tickLabels(0, 60_000)).toEqual(["CA$0", "CA$15K", "CA$30K", "CA$45K", "CA$60K"]);
    });
});

describe("chart summaries for screen readers", () => {
    const money = (v) => formatMoney(v, "CAD");
    const points = [{price: 2}, {price: 5}, {price: 1}, {price: 3}];

    it("gives the first, last, high and low", () => {
        expect(normalize(chartSummary("BTC price", "over the past month", points, "price", money)))
            .toBe("BTC price over the past month: from CA$2.00 to CA$3.00, high CA$5.00, low CA$1.00.");
    });

    it("skips missing values and handles one or no points", () => {
        expect(normalize(chartSummary("X", "over the past day", [{price: null}, {price: 4}], "price", money)))
            .toBe("X over the past day: CA$4.00.");
        expect(chartSummary("X", "over the past day", [], "price", money)).toBe("X over the past day: no data.");
        expect(chartSummary("X", "", undefined, "price", money)).toBe("X: no data.");
    });

    it("words each price chart range", () => {
        for (const range of ["1D", "1W", "1M", "1Y", "5Y"]) {
            expect(priceChartSummary("AAPL", range, null, points, money))
                .toMatch(new RegExp(`^AAPL price ${RANGE_PHRASES[range]}: from `));
        }
    });

    it("describes the range the prices really cover (CoinGecko's 5Y is one year)", () => {
        expect(priceChartSummary("PEPE", "5Y", "1Y", points, money)).toMatch(/^PEPE price over the past year: /);
        expect(priceChartSummary("PEPE", "5Y", null, points, money)).toMatch(/^PEPE price over the past 5 years: /);
    });
});
