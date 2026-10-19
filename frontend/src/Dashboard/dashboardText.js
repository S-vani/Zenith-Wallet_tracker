// Text shown or read out on the dashboard (pure, tested in test/dashboardText.test.js)
import {formatMoney} from "../utils/format.js";
import {RANGE_PHRASES, chartSummary} from "../utils/chart.js";

// the dashboard's range values -> the shared range names used for the chart summary
const RANGE_KEYS = {day: "1D", week: "1W", month: "1M", year: "1Y", all: "All"};

// What a screen reader gets instead of the chart: the value line, then the invested line when there is one
export function dashboardChartSummary(data, range, currency) {
    const phrase = RANGE_PHRASES[RANGE_KEYS[range]] ?? "";
    const money = (v) => formatMoney(v, currency);
    const value = chartSummary("Portfolio value", phrase, data, "value", money);
    const hasInvested = (data ?? []).some((d) => Number.isFinite(d?.invested));
    return hasInvested
        ? `${value} ${chartSummary("Amount invested in what you hold", "", data, "invested", money)}`
        : value;
}

// /dashboard lists holdings no source has a price for in `unpriced`; they're left out of the value and returns, so
// say which ones instead of letting the totals look complete. Null when everything is priced.
const SHOWN = 3; // after this many tickers: "and 2 others"

export function unpricedNote(unpriced) {
    const symbols = [...new Set((unpriced ?? []).map((s) => String(s).toUpperCase()).filter(Boolean))];
    if (symbols.length === 0) return null;

    let names;
    if (symbols.length === 1) {
        names = symbols[0];
    } else if (symbols.length <= SHOWN) {
        names = `${symbols.slice(0, -1).join(", ")} and ${symbols[symbols.length - 1]}`;
    } else {
        const others = symbols.length - SHOWN;
        names = `${symbols.slice(0, SHOWN).join(", ")} and ${others} other${others === 1 ? "" : "s"}`;
    }

    return symbols.length === 1
        ? `${names} has no price right now and isn't included in the totals.`
        : `${names} have no price right now and aren't included in the totals.`;
}
