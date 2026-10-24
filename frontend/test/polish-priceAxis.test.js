import {describe, expect, it} from "vitest";
import {axisMoneyOptions, niceAxis} from "../src/utils/chart.js";
import {passwordRulesMet} from "../src/Authentication/passwordRules.js";

// HoldingsChart's y axis: niceAxis without headroom, 5 ticks (4 in the add-trade sheet), labels from the step
const priceAxis = (prices, compact = false) => {
    const yAxis = niceAxis(prices, compact ? 4 : 5);
    return {yAxis, options: axisMoneyOptions(yAxis.ticks, yAxis.step)};
};

describe("price chart y axis", () => {
    it("rounds to a nice step and stays tight around the prices", () => {
        const prices = [187.3, 191.05, 189.9, 195.42];
        const {yAxis} = priceAxis(prices);
        expect(yAxis.ticks.length).toBeLessThanOrEqual(5);
        expect(yAxis.domain[0]).toBeLessThanOrEqual(187.3);
        expect(yAxis.domain[1]).toBeGreaterThanOrEqual(195.42);
        // no headroom: the axis spans at most one extra step past each end of the data
        expect(yAxis.domain[0]).toBeGreaterThan(187.3 - yAxis.step);
        expect(yAxis.domain[1]).toBeLessThan(195.42 + yAxis.step);
        yAxis.ticks.forEach((t) => expect(Number((t / yAxis.step).toFixed(6)) % 1).toBe(0));
    });

    it("gives the compact chart no more than 4 ticks", () => {
        expect(priceAxis([0.98, 1.31, 1.07, 1.52], true).yAxis.ticks.length).toBeLessThanOrEqual(4);
    });

    it("labels small coin prices with enough decimals to tell the ticks apart", () => {
        const {yAxis, options} = priceAxis([0.0021, 0.00228, 0.0023]);
        expect(yAxis.domain[0]).toBeGreaterThan(0);
        expect(new Set(yAxis.ticks).size).toBe(yAxis.ticks.length);
        expect(options.maximumFractionDigits).toBeGreaterThanOrEqual(4);
    });
});

describe("change password checklist", () => {
    it("refuses the account's own email as the new password", () => {
        expect(passwordRulesMet("Me@Example.com", "me@example.com")).toBe(false);
        expect(passwordRulesMet("a-better-pass", "me@example.com")).toBe(true);
    });
});
