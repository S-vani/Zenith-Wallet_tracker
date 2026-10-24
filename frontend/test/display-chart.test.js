import {describe, expect, it} from "vitest";
import {axisMoneyOptions, niceAxis, niceStep} from "../src/utils/chart.js";
import {formatMoney} from "../src/utils/format.js";

// Dashboard y axis: round ticks instead of recharts' "auto" ones (CA$7K / 13K / 20K / 26K)

const labels = (values) => {
    const axis = niceAxis(values);
    const options = axisMoneyOptions(axis.ticks, axis.step);
    return axis.ticks.map((v) => formatMoney(v, "CAD", options));
};

describe("niceStep", () => {
    it.each([
        [0.7, 1],
        [1, 1],
        [1.3, 2],
        [2.2, 2.5],
        [3, 5],
        [6625, 10000],
        [425, 500],
        [0.00013, 0.0002],
    ])("rounds %s up to %s", (raw, expected) => {
        expect(niceStep(raw)).toBeCloseTo(expected, 12);
    });

    it("falls back to 1 for nothing usable", () => {
        expect(niceStep(0)).toBe(1);
        expect(niceStep(NaN)).toBe(1);
        expect(niceStep(-5)).toBe(1);
    });
});

describe("niceAxis", () => {
    it("turns 0 to 26.5K into round ten-thousands", () => {
        const axis = niceAxis([0, 6900, 26500]);
        expect(axis.ticks).toEqual([0, 10000, 20000, 30000]);
        expect(axis.domain).toEqual([0, 30000]);
        expect(labels([0, 6900, 26500])).toEqual(["CA$0", "CA$10K", "CA$20K", "CA$30K"]);
    });

    it("turns 22.1K to 23.8K into half-thousands", () => {
        expect(niceAxis([22100, 23800]).ticks).toEqual([22000, 22500, 23000, 23500, 24000]);
        expect(labels([22100, 23800])).toEqual(["CA$22K", "CA$22.5K", "CA$23K", "CA$23.5K", "CA$24K"]);
    });

    it("keeps the decimal of a 2.5 step", () => {
        const axis = niceAxis([0, 9000]);
        expect(axis.step).toBe(2500);
        expect(labels([0, 9000])).toEqual(["CA$0", "CA$2.5K", "CA$5K", "CA$7.5K", "CA$10K"]);
    });

    it("never has more than the requested number of ticks and always covers every value", () => {
        for (const [low, high] of [[0, 1], [3, 97], [1234, 98765], [0.0012, 0.0019], [480, 520], [1e9, 4.2e9]]) {
            const axis = niceAxis([low, high]);
            expect(axis.ticks.length).toBeLessThanOrEqual(5);
            expect(axis.ticks.length).toBeGreaterThanOrEqual(2);
            expect(axis.domain[0]).toBeLessThanOrEqual(low);
            expect(axis.domain[1]).toBeGreaterThanOrEqual(high);
        }
    });

    it("has evenly spaced ticks with no floating point noise", () => {
        const axis = niceAxis([0.1, 0.7]);
        expect(axis.ticks).toEqual([0, 0.2, 0.4, 0.6, 0.8]);
    });

    it("doesn't dip below zero for positive values", () => {
        expect(niceAxis([5, 95]).domain[0]).toBe(0);
        expect(niceAxis([500, 520]).domain[0]).toBeGreaterThan(0);
    });

    it("gives a flat line some room", () => {
        const axis = niceAxis([1000, 1000]);
        expect(axis.domain[0]).toBeLessThan(1000);
        expect(axis.domain[1]).toBeGreaterThan(1000);
        expect(niceAxis([0, 0]).domain).toEqual([0, 1]);
    });

    it("ignores missing values and is null without any", () => {
        expect(niceAxis([null, undefined, NaN, "", 10, 30]).ticks).toEqual([10, 15, 20, 25, 30]);
        expect(niceAxis([])).toBeNull();
        expect(niceAxis([null, NaN])).toBeNull();
        expect(niceAxis(undefined)).toBeNull();
    });

    it("labels every tick differently for small amounts", () => {
        const shown = labels([1.405, 1.415]);
        expect(new Set(shown).size).toBe(shown.length);
    });
});
