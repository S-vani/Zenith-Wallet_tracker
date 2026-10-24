import {describe, expect, it} from "vitest";
import {clockOffset, formatCountdown, formatRelativeTime} from "../src/Analyst/analystUtils.js";

const NOW = Date.UTC(2026, 9, 24, 15, 0, 0);
const MINUTE = 60 * 1000;
const iso = (ms) => new Date(ms).toISOString();

describe("analyst 'Updated' wording", () => {
    it("says just now for anything under a minute", () => {
        expect(formatRelativeTime(iso(NOW - 59 * 1000), NOW)).toBe("just now");
        expect(formatRelativeTime(iso(NOW - MINUTE), NOW)).toBe("1 min ago");
    });
});

describe("refresh countdown", () => {
    it("rounds up, so it never shows less time than is left", () => {
        // ten seconds after a refresh with a 5 minute cooldown
        expect(formatCountdown(iso(NOW + 5 * MINUTE - 10 * 1000), NOW)).toBe("5 min");
        expect(formatCountdown(iso(NOW + 4 * MINUTE + 1000), NOW)).toBe("5 min");
        expect(formatCountdown(iso(NOW + 1000), NOW)).toBe("1 min");
    });
});

describe("clockOffset", () => {
    const fresh = (generatedAgo) => ({cached: false, generated_at: iso(NOW - generatedAgo)});

    it("measures how far a fast device clock is ahead from a just-generated report", () => {
        expect(clockOffset(fresh(70 * 1000), NOW)).toBe(70 * 1000);
    });

    it("keeps 'just now' and the full cooldown when the device clock is fast", () => {
        const report = {...fresh(70 * 1000), refresh_available_at: iso(NOW - 70 * 1000 + 5 * MINUTE)};
        const offset = clockOffset(report, NOW);
        const shownNow = NOW + 10 * 1000; // ten seconds later
        expect(formatRelativeTime(report.generated_at, shownNow - offset)).toBe("just now");
        expect(formatCountdown(Date.parse(report.refresh_available_at) + offset, shownNow)).toBe("5 min");
    });

    it("is 0 for cached reports, a slow device clock or a missing date", () => {
        expect(clockOffset({cached: true, generated_at: iso(NOW - 3 * MINUTE)}, NOW)).toBe(0);
        expect(clockOffset({generated_at: iso(NOW - 3 * MINUTE)}, NOW)).toBe(0);
        expect(clockOffset(fresh(-30 * 1000), NOW)).toBe(0);
        expect(clockOffset({cached: false, generated_at: null}, NOW)).toBe(0);
        expect(clockOffset(null, NOW)).toBe(0);
    });

    it("is capped so a broken timestamp can't hold the button for long", () => {
        expect(clockOffset(fresh(3 * 24 * 60 * MINUTE), NOW)).toBe(10 * MINUTE);
    });
});
