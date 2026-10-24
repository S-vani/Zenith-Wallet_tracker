// Shared chart helpers so the dashboard, holdings and search charts behave the same

export const TOOLTIP_STYLE = {
    background: "#0f1520",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: "0.625rem",
    fontSize: "0.8rem",
    color: "#f5f7ff",
};

export const CHART_UP = "#22c55e";
export const CHART_DOWN = "#ef4444";
// the dashboard's "invested" line: faint and dashed so the value line stays the main one
export const CHART_INVESTED = "#94a3b8";

// How each chart range reads in a screen reader summary ("Portfolio value over the past year: …")
export const RANGE_PHRASES = {
    "1D": "over the past day",
    "1W": "over the past week",
    "1M": "over the past month",
    "1Y": "over the past year",
    "5Y": "over the past 5 years",
    All: "since you joined",
};

// Avoids recharts' "width(-1) and height(-1)" warning on the first render
export const INITIAL_DIMENSION = {width: 1, height: 1};

// Fixed English abbreviations: the browser's own ("Sept" in en-CA, "Sep" in en-US) made labels inconsistent
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const DAY_MS = 24 * 60 * 60 * 1000;

const toMs = (value) => new Date(value).getTime();

// Hourly data over a week otherwise repeats the same date label several times; put one tick at the start of each day
export function dailyTicks(data, key = "time") {
    let lastDay = null;
    const ticks = [];
    for (const point of data) {
        const day = new Date(point[key]).toDateString();
        if (day !== lastDay) {
            ticks.push(point[key]);
            lastDay = day;
        }
    }
    return ticks;
}

// What the x axis is labelled with, from how much time the data covers:
// "time" (a day or less: 2:30 PM), "day" (up to ~3 months: Oct 5) or "month" (longer: Oct ’25)
export function tickUnit(data, key = "time") {
    if (!data || data.length < 2) return "time";
    const spanDays = (toMs(data[data.length - 1][key]) - toMs(data[0][key])) / DAY_MS;
    if (spanDays <= 1.5) return "time";
    if (spanDays <= 100) return "day";
    return "month";
}

function bucketOf(value, unit) {
    const date = new Date(value);
    return unit === "month" ? `${date.getFullYear()}-${date.getMonth()}` : date.toDateString();
}

// One tick at the first point of each local day / month, so no two ticks can share a label, thinned to about
// `maxTicks`. Intraday charts return undefined and let recharts space the times itself.
export function axisTicks(data, unit, key = "time", maxTicks = 8) {
    if (unit === "time" || !data || data.length === 0) return undefined;

    const starts = [];
    let last = null;
    for (const point of data) {
        const bucket = bucketOf(point[key], unit);
        if (bucket !== last) {
            starts.push(point[key]);
            last = bucket;
        }
    }

    // data that starts late in a day / month (e.g. joined Oct 28) would squeeze "Oct ’25" right next to "Nov ’25"
    if (starts.length > 2) {
        const firstGap = toMs(starts[1]) - toMs(starts[0]);
        const nextGap = toMs(starts[2]) - toMs(starts[1]);
        if (firstGap < nextGap / 2) starts.shift();
    }

    if (starts.length <= maxTicks) return starts;
    // evenly spaced, counted back from the newest so the most recent label is always shown
    const step = Math.ceil(starts.length / maxTicks);
    const kept = [];
    for (let i = starts.length - 1; i >= 0; i -= step) kept.unshift(starts[i]);
    return kept;
}

// Label for one x axis tick in the given unit
export function formatAxisTick(value, unit) {
    const date = new Date(value);
    if (unit === "time") return date.toLocaleString(undefined, {hour: "numeric", minute: "2-digit"});
    const month = MONTHS[date.getMonth()];
    if (unit === "month") return `${month} ’${String(date.getFullYear()).slice(-2)}`;
    return `${month} ${date.getDate()}`;
}

// Intraday ranges show a time, longer ranges are daily candles so only the date is meaningful
export function tooltipDate(value, intraday) {
    const date = new Date(value);
    const day = `${MONTHS[date.getMonth()]} ${date.getDate()}`;
    return intraday
        ? `${day}, ${date.toLocaleString(undefined, {hour: "numeric", minute: "2-digit"})}`
        : `${day}, ${date.getFullYear()}`;
}

// Decimals needed to tell apart ticks that are `step` apart (0 for steps of 1 or more)
function decimalsFor(step) {
    if (!(step > 0)) return 2;
    return Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
}

// Decimals a tick step really has (2.5 → 1, 0.25 → 2, 500 → 0), allowing for floating point noise
function exactDecimals(step) {
    for (let d = 0; d <= 20; d++) {
        const scaled = step * 10 ** d;
        const whole = Math.round(scaled);
        // relative to the step itself: an absolute tolerance treated tiny steps (a PEPE axis, 0.0000005) as whole
        // numbers, so every tick rounded to 0
        if (whole !== 0 && Math.abs(scaled - whole) < 1e-9 * Math.abs(scaled)) return d;
    }
    return 20;
}

// The smallest "nice" step (1, 2, 2.5 or 5 × 10^n) of at least `raw`
export function niceStep(raw) {
    if (!(raw > 0) || !Number.isFinite(raw)) return 1;
    const power = 10 ** Math.floor(Math.log10(raw));
    const fraction = raw / power;
    const mantissa = [1, 2, 2.5, 5, 10].find((m) => fraction <= m * (1 + 1e-9));
    return mantissa * power;
}

// Round y axis ticks for these values: recharts' "auto" domain gave labels like CA$7K / 13K / 20K / 26K. Returns
// {domain: [low, high], ticks, step} with at most `maxTicks` ticks a nice step apart that cover every value, or null
// without any finite value (then the chart keeps recharts' own axis). Never dips below 0 for values that don't.
// `headroom` (a share of the largest value, e.g. 0.1) widens the range above and below the data before rounding, so
// two lines a few percent apart (portfolio value vs invested) don't fill the chart from top to bottom.
export function niceAxis(values, maxTicks = 5, {headroom = 0} = {}) {
    const numbers = (values ?? []).filter((v) => v !== null && v !== undefined && v !== "")
        .map(Number).filter(Number.isFinite);
    if (numbers.length === 0) return null;

    let min = Math.min(...numbers);
    let max = Math.max(...numbers);
    if (headroom > 0) {
        const pad = Math.max(Math.abs(min), Math.abs(max)) * headroom;
        // money that never went below 0 shouldn't get a negative axis
        min = min >= 0 ? Math.max(0, min - pad) : min - pad;
        max += pad;
    }
    if (min === max) {
        // a flat line: give it some room around the value (or 0 to 1 for all zeros)
        const pad = Math.abs(max) * 0.05 || 1;
        min = min >= 0 ? Math.max(0, min - pad) : min - pad;
        max += pad;
    }

    const count = Math.max(2, maxTicks);
    let step = niceStep((max - min) / (count - 1));
    let low = Math.floor(min / step) * step;
    let high = Math.ceil(max / step) * step;
    // rounding the ends outwards can add a tick; step up until they fit
    while (Math.round((high - low) / step) + 1 > count) {
        step = niceStep(step * 1.01);
        low = Math.floor(min / step) * step;
        high = Math.ceil(max / step) * step;
    }

    // rounded to the step's decimals so floating point noise (0.30000000000000004) never reaches a label
    const decimals = Math.min(20, exactDecimals(step));
    const clean = (v) => Number(v.toFixed(decimals)) || 0; // || 0: no "-0"
    const ticks = [];
    for (let i = 0; i <= Math.round((high - low) / step); i++) ticks.push(clean(low + i * step));
    return {domain: [ticks[0], ticks[ticks.length - 1]], ticks, step};
}

// formatMoney options for a y axis showing these values: every tick gets the same number of decimals, and enough of
// them that neighbouring ticks never read the same (a stablecoin moving between CA$1.405 and CA$1.415 needs 3).
// Big values use compact labels (CA$114.5K) unless the range is too narrow for them to differ.
// `tickStep` is the exact distance between ticks when the axis has fixed ones (niceAxis): a 2.5K step then keeps
// its decimal ("CA$7.5K", never "CA$8K").
export function axisMoneyOptions(values, tickStep) {
    const numbers = (values ?? []).map(Number).filter(Number.isFinite);
    if (numbers.length === 0) return {minimumFractionDigits: 0, maximumFractionDigits: 0};

    const exact = tickStep > 0;
    const places = exact ? exactDecimals : decimalsFor;
    const max = Math.max(...numbers.map(Math.abs));
    const spread = exact ? tickStep : Math.max(...numbers) - Math.min(...numbers);
    const step = exact ? tickStep : spread / 4; // recharts draws about five ticks

    if (max >= 10_000) {
        const unit = max >= 1e12 ? 1e12 : max >= 1e9 ? 1e9 : max >= 1e6 ? 1e6 : 1e3;
        const digits = spread > 0 ? places(step / unit) : 1;
        if (digits <= 1) return {notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: digits};
        // compact labels would all read "CA$114k", so show the full amount instead
    }

    const digits = spread > 0 ? places(step) : (max >= 1 ? 2 : decimalsFor(max / 1000));
    // whole dollars, or at least cents ("CA$766.50", never "CA$766.5")
    const decimals = digits === 0 ? 0 : Math.min(12, Math.max(2, digits));
    return {minimumFractionDigits: decimals, maximumFractionDigits: decimals};
}

// Text a screen reader can read instead of the chart's picture, e.g. "Portfolio value over the past year: from
// CA$12,000 to CA$53,900, high CA$56,000, low CA$11,500." `format` turns a number into money text.
export function chartSummary(title, phrase, data, key, format) {
    // null is a missing price, not 0 (Number(null) would make it one)
    const values = (data ?? []).map((d) => d?.[key]).filter((v) => v !== null && v !== undefined && v !== "")
        .map(Number).filter(Number.isFinite);
    const span = phrase ? `${title} ${phrase}` : title;
    if (values.length === 0) return `${span}: no data.`;

    const first = format(values[0]);
    const last = format(values[values.length - 1]);
    if (values.length === 1) return `${span}: ${last}.`;
    return `${span}: from ${first} to ${last}, high ${format(Math.max(...values))}, low ${format(Math.min(...values))}.`;
}

// Summary for a holding / search price chart. `covered` is the range the prices really cover when it's shorter than
// the one asked for (CoinGecko's free plan stops at a year, so its "5Y" is one year), so the text never overstates.
export function priceChartSummary(label, range, covered, data, format) {
    return chartSummary(`${label} price`, RANGE_PHRASES[covered || range] ?? "", data, "price", format);
}
