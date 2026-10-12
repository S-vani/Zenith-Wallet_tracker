import {describe, expect, it} from "vitest";
import {
    analystRequestKey,
    confidenceMeta,
    createLatestRequestTracker,
    daysUntil,
    engineMeta,
    fetchLatest,
    formatCountdown,
    formatDate,
    formatEventDate,
    formatPeriod,
    formatRelativeTime,
    formatScore,
    formatShortPercent,
    formatTimestamp,
    groupMetrics,
    humanize,
    orderScenarios,
    parseDate,
    percentFrom,
    safeUrl,
    scenarioRanges,
    scorePosition,
    sentimentMeta,
    toneClass,
} from "../src/Analyst/analystUtils.js";

// test/setup.js pins en-US and America/Toronto
const NOW = Date.parse("2026-10-12T18:00:00Z"); // 2:00 PM in Toronto

describe("parseDate", () => {
    it("reads ISO strings with a zone", () => {
        expect(parseDate("2026-10-12T14:05:00+00:00").toISOString()).toBe("2026-10-12T14:05:00.000Z");
        expect(parseDate("2026-10-12T14:05:00Z").toISOString()).toBe("2026-10-12T14:05:00.000Z");
    });

    it("treats values without a zone as UTC", () => {
        expect(parseDate("2026-10-12T14:05:00").toISOString()).toBe("2026-10-12T14:05:00.000Z");
        expect(parseDate("2026-10-12T14:05:00.123456").toISOString()).toBe("2026-10-12T14:05:00.123Z");
        expect(parseDate("2026-10-12").toISOString()).toBe("2026-10-12T00:00:00.000Z");
    });

    it("accepts epoch milliseconds and Date objects", () => {
        expect(parseDate(NOW).getTime()).toBe(NOW);
        expect(parseDate(new Date(NOW)).getTime()).toBe(NOW);
    });

    it.each([null, undefined, "", "not a date", NaN, new Date("nope")])("returns null for %j", (value) => {
        expect(parseDate(value)).toBeNull();
    });
});

describe("formatRelativeTime", () => {
    it.each([
        [10 * 1000, "just now"],
        [50 * 1000, "1 min ago"],
        [3 * 60 * 1000, "3 min ago"],
        [59 * 60 * 1000, "59 min ago"],
        [2 * 3600 * 1000 + 5 * 60 * 1000, "2 hr ago"],
        [30 * 3600 * 1000, "yesterday"],
        [5 * 24 * 3600 * 1000, "5 days ago"],
    ])("%d ms ago -> %s", (ago, expected) => {
        expect(formatRelativeTime(new Date(NOW - ago).toISOString(), NOW)).toBe(expected);
    });

    it("never shows a future time for a fast server clock", () => {
        expect(formatRelativeTime(new Date(NOW + 90 * 1000).toISOString(), NOW)).toBe("just now");
    });

    it("is empty without a date", () => {
        expect(formatRelativeTime(null, NOW)).toBe("");
    });
});

describe("date formatting", () => {
    it("formats a full timestamp in local time", () => {
        expect(formatTimestamp("2026-10-12T18:05:00Z")).toMatch(/^Oct 12, 2026, 2:05\sPM$/);
    });

    it("keeps calendar dates (midnight UTC) on the same day in the Americas", () => {
        expect(formatDate("2025-10-12T00:00:00Z")).toBe("Oct 12, 2025");
        expect(formatDate("2025-10-12")).toBe("Oct 12, 2025");
    });

    it("uses local time for real timestamps", () => {
        // 02:00 UTC on Oct 13 is still Oct 12 in Toronto
        expect(formatDate("2025-10-13T02:00:00Z")).toBe("Oct 12, 2025");
    });

    it("formats the data period", () => {
        expect(formatPeriod({start: "2025-10-12T00:00:00Z", end: "2026-10-11T00:00:00Z", days: 364}))
            .toBe("Oct 12, 2025 – Oct 11, 2026");
        expect(formatPeriod({start: "2026-10-11T00:00:00Z", end: "2026-10-11T00:00:00Z", days: 0}))
            .toBe("Oct 11, 2026");
        expect(formatPeriod(null)).toBe("");
    });
});

describe("event dates", () => {
    it("counts calendar days until an event", () => {
        expect(daysUntil("2026-10-12T00:00:00Z", NOW)).toBe(0);
        expect(daysUntil("2026-10-13T00:00:00Z", NOW)).toBe(1);
        expect(daysUntil("2026-10-29T00:00:00Z", NOW)).toBe(17);
        expect(daysUntil("2026-10-10T00:00:00Z", NOW)).toBe(-2);
        expect(daysUntil(null, NOW)).toBeNull();
    });

    it("labels the date with weekday and how far away it is", () => {
        expect(formatEventDate("2026-10-29T00:00:00Z", NOW)).toEqual({label: "Thu, Oct 29, 2026", relative: "in 17 days"});
        expect(formatEventDate("2026-10-12T00:00:00Z", NOW).relative).toBe("today");
        expect(formatEventDate("2026-10-13T00:00:00Z", NOW).relative).toBe("tomorrow");
        expect(formatEventDate("2026-10-11T00:00:00Z", NOW).relative).toBe("yesterday");
        expect(formatEventDate("2026-10-08T00:00:00Z", NOW).relative).toBe("4 days ago");
        expect(formatEventDate(null, NOW)).toBeNull();
    });
});

describe("formatCountdown", () => {
    it.each([
        [20 * 1000, "1 min"],
        [4 * 60 * 1000, "4 min"],
        [4 * 60 * 1000 + 1, "5 min"],
        [60 * 60 * 1000, "1 hr"],
        [65 * 60 * 1000, "1 hr 5 min"],
    ])("%d ms left -> %s", (left, expected) => {
        expect(formatCountdown(new Date(NOW + left).toISOString(), NOW)).toBe(expected);
    });

    it("accepts epoch milliseconds", () => {
        expect(formatCountdown(NOW + 4 * 60 * 1000, NOW)).toBe("4 min");
    });

    it("is null once a refresh is allowed or without a time", () => {
        expect(formatCountdown(new Date(NOW).toISOString(), NOW)).toBeNull();
        expect(formatCountdown(new Date(NOW - 5000).toISOString(), NOW)).toBeNull();
        expect(formatCountdown(null, NOW)).toBeNull();
    });
});

describe("labels and classes", () => {
    it("maps sentiment to a label and class", () => {
        expect(sentimentMeta("bullish")).toEqual({label: "Bullish", className: "bullish"});
        expect(sentimentMeta("neutral")).toEqual({label: "Neutral", className: "neutral"});
        expect(sentimentMeta("bearish")).toEqual({label: "Bearish", className: "bearish"});
        expect(sentimentMeta(null)).toBeNull();
        expect(sentimentMeta("moon")).toBeNull();
    });

    it("maps confidence to a 3 step level", () => {
        expect(confidenceMeta("low")).toEqual({label: "Low confidence", level: 1});
        expect(confidenceMeta("medium")).toEqual({label: "Medium confidence", level: 2});
        expect(confidenceMeta("high")).toEqual({label: "High confidence", level: 3});
        expect(confidenceMeta(null)).toBeNull();
    });

    it.each([["positive", "positive"], ["negative", "negative"], ["neutral", "neutral"], [undefined, "neutral"],
        ["weird", "neutral"]])("tone %j -> %s", (tone, expected) => {
        expect(toneClass(tone)).toBe(expected);
    });

    it("labels the engine honestly", () => {
        expect(engineMeta("rules").label).toBe("Rules-based analysis");
        expect(engineMeta("gemini").label).toBe("AI-written · Gemini");
        expect(engineMeta(undefined).label).toBe("Rules-based analysis");
    });

    it("humanizes kinds", () => {
        expect(humanize("price_level")).toBe("Price level");
        expect(humanize("momentum")).toBe("Momentum");
        expect(humanize("")).toBe("");
    });
});

describe("score", () => {
    it("maps -1..1 onto the gauge and clamps", () => {
        expect(scorePosition(-1)).toBe(0);
        expect(scorePosition(0)).toBe(50);
        expect(scorePosition(0.5)).toBe(75);
        expect(scorePosition(3)).toBe(100);
        expect(scorePosition(-3)).toBe(0);
    });

    it.each([null, undefined, NaN, "abc"])("has no position for %j", (value) => {
        expect(scorePosition(value)).toBeNull();
    });

    it("formats with a sign", () => {
        expect(formatScore(0.423)).toBe("+0.42");
        expect(formatScore(-0.4)).toBe("−0.40");
        expect(formatScore(0)).toBe("0.00");
        expect(formatScore(null)).toBe("");
    });
});

describe("scenarios", () => {
    it("orders bull, base, bear and drops unknown cases", () => {
        const ordered = orderScenarios([{case: "bear"}, {case: "moon"}, {case: "bull"}, {case: "base"}]);
        expect(ordered.map((s) => s.case)).toEqual(["bull", "base", "bear"]);
        expect(ordered.map((s) => s.label)).toEqual(["Bull case", "Base case", "Bear case"]);
        expect(orderScenarios(undefined)).toEqual([]);
    });

    it("sorts ranges by horizon and skips broken ones", () => {
        const ranges = scenarioRanges({
            ranges: [{days: 30, low: 90, high: 120}, {days: 7, low: 105, high: 98}, {days: 7, low: null, high: 1}],
        });
        expect(ranges).toEqual([{days: 7, low: 98, high: 105}, {days: 30, low: 90, high: 120}]);
        expect(scenarioRanges({ranges: []})).toEqual([]);
        expect(scenarioRanges(undefined)).toEqual([]);
    });

    it("computes the move from the current price", () => {
        expect(percentFrom(95, 100)).toBe(-5);
        expect(percentFrom(112, 100)).toBeCloseTo(12);
        expect(percentFrom(10, 0)).toBeNull();
        expect(percentFrom(10, null)).toBeNull();
        expect(formatShortPercent(-4.83)).toBe("−4.8%");
        expect(formatShortPercent(12.4)).toBe("+12%");
        expect(formatShortPercent(0.01)).toBe("0%");
        expect(formatShortPercent(null)).toBe("");
    });
});

describe("groupMetrics", () => {
    it("groups in a fixed order and keeps the order within a group", () => {
        const groups = groupMetrics([
            {label: "RSI (14)", value: "62", group: "trend"},
            {label: "30-day return", value: "+12.4%", group: "performance"},
            {label: "Above 200-day average", value: "Yes", group: "trend"},
            {label: "Mystery", value: "1", group: "sentiment_extra"},
            {label: "", value: "skipped", group: "risk"},
        ]);
        expect(groups.map((g) => g.group)).toEqual(["performance", "trend", "sentiment_extra"]);
        expect(groups[1].label).toBe("Trend");
        expect(groups[1].items.map((m) => m.label)).toEqual(["RSI (14)", "Above 200-day average"]);
        expect(groups[2].label).toBe("Sentiment extra");
    });

    it("handles no metrics", () => {
        expect(groupMetrics(undefined)).toEqual([]);
        expect(groupMetrics([])).toEqual([]);
    });
});

describe("safeUrl", () => {
    it("only allows http(s) links", () => {
        expect(safeUrl("https://finance.yahoo.com/quote/AAPL")).toBe("https://finance.yahoo.com/quote/AAPL");
        expect(safeUrl("javascript:alert(1)")).toBeNull();
        expect(safeUrl("not a url")).toBeNull();
        expect(safeUrl(null)).toBeNull();
    });
});

describe("analystRequestKey", () => {
    it("differs per asset, type and coin id", () => {
        const keys = new Set([
            analystRequestKey({symbol: "BTC", type: "crypto", coinId: "bitcoin"}),
            analystRequestKey({symbol: "BTC", type: "crypto", coinId: "batcat"}),
            analystRequestKey({symbol: "BTC", type: "stock"}),
            analystRequestKey({symbol: "ETH", type: "crypto"}),
        ]);
        expect(keys.size).toBe(4);
        expect(analystRequestKey({symbol: "AAPL", type: "stock"})).toBe(analystRequestKey({symbol: "AAPL", type: "stock"}));
    });
});

// A promise we can settle from the test, to control the order responses arrive in
function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return {promise, resolve, reject};
}

describe("switching assets (stale response guard)", () => {
    it("aborts the previous request when a new one starts", () => {
        const tracker = createLatestRequestTracker();
        const first = tracker.start();
        const second = tracker.start();

        expect(first.signal.aborted).toBe(true);
        expect(first.isCurrent()).toBe(false);
        expect(second.signal.aborted).toBe(false);
        expect(second.isCurrent()).toBe(true);

        tracker.cancel();
        expect(second.signal.aborted).toBe(true);
        expect(second.isCurrent()).toBe(false);
    });

    it("drops a late response for the previous asset, even if it ignored the abort", async () => {
        const tracker = createLatestRequestTracker();
        const btc = deferred();
        const eth = deferred();

        const btcResult = fetchLatest(tracker, () => btc.promise); // user opened BTC
        const ethResult = fetchLatest(tracker, () => eth.promise); // ...then switched to ETH

        eth.resolve({asset: {symbol: "ETH"}});
        btc.resolve({asset: {symbol: "BTC"}}); // arrives last

        expect(await ethResult).toEqual({status: "ok", data: {asset: {symbol: "ETH"}}});
        expect(await btcResult).toEqual({status: "superseded"});
    });

    it("ignores errors from superseded and aborted requests", async () => {
        const tracker = createLatestRequestTracker();
        const old = deferred();
        const oldResult = fetchLatest(tracker, (signal) => {
            signal.addEventListener("abort", () => old.reject(new DOMException("aborted", "AbortError")));
            return old.promise;
        });
        const current = fetchLatest(tracker, async () => {
            throw Object.assign(new Error("Too many requests"), {status: 429});
        });

        expect(await oldResult).toEqual({status: "superseded"});
        const res = await current;
        expect(res.status).toBe("error");
        expect(res.error).toMatchObject({message: "Too many requests", status: 429});
    });

    it("drops everything after the panel closes", async () => {
        const tracker = createLatestRequestTracker();
        const pending = deferred();
        const result = fetchLatest(tracker, () => pending.promise);
        tracker.cancel();
        pending.resolve({status: "ok"});
        expect(await result).toEqual({status: "superseded"});
    });
});
