// Pure helpers for the Market Analyst panel: date/time wording, label + colour mapping and request bookkeeping.
// Kept free of React so they can be unit tested (test/analystUtils.test.js).

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// The API sends ISO datetimes in UTC. Treat a value without a zone as UTC too, so it isn't read as local time
export function parseDate(value) {
    if (value === null || value === undefined || value === "") return null;
    if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
    if (typeof value === "number") return Number.isFinite(value) ? new Date(value) : null; // epoch ms

    let text = String(value);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T00:00:00Z";
    else if (/^\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(text)) text += "Z";

    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
}

// A datetime at exactly midnight UTC is a calendar date (daily bars, earnings days). Showing it in the reader's
// zone would move it to the evening before in the Americas, so those are formatted in UTC
function isCalendarDate(date) {
    return date.getUTCHours() === 0 && date.getUTCMinutes() === 0 && date.getUTCSeconds() === 0
        && date.getUTCMilliseconds() === 0;
}

function formatDay(date, options) {
    return date.toLocaleString(undefined, {...options, ...(isCalendarDate(date) ? {timeZone: "UTC"} : {})});
}

// "just now", "3 min ago", "2 hr ago", "yesterday", "5 days ago"
export function formatRelativeTime(value, now = Date.now()) {
    const date = parseDate(value);
    if (!date) return "";

    const diff = Math.max(0, now - date.getTime()); // a slightly fast server clock shouldn't say "in 1 min"
    if (diff < 45 * 1000) return "just now";
    if (diff < HOUR) return `${Math.max(1, Math.round(diff / MINUTE))} min ago`;
    if (diff < DAY) return `${Math.floor(diff / HOUR)} hr ago`;
    if (diff < 2 * DAY) return "yesterday";
    return `${Math.floor(diff / DAY)} days ago`;
}

// Full timestamp for title attributes, e.g. "Oct 12, 2026, 2:05 PM"
export function formatTimestamp(value) {
    const date = parseDate(value);
    if (!date) return "";
    return date.toLocaleString(undefined, {
        month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
    });
}

// "Oct 12, 2025"
export function formatDate(value) {
    const date = parseDate(value);
    if (!date) return "";
    return formatDay(date, {month: "short", day: "numeric", year: "numeric"});
}

// "Oct 12, 2025 – Oct 11, 2026" for the period the analysis covers
export function formatPeriod(period) {
    if (!period) return "";
    const start = formatDate(period.start);
    const end = formatDate(period.end);
    if (!start || !end) return start || end;
    return start === end ? start : `${start} – ${end}`;
}

// Whole calendar days from today until a date (negative when it has passed)
export function daysUntil(value, now = Date.now()) {
    const date = parseDate(value);
    if (!date) return null;

    const target = isCalendarDate(date)
        ? Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
        : Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
    const today = new Date(now);
    return Math.round((target - Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / DAY);
}

// Date of an upcoming event: {label: "Thu, Oct 29, 2026", relative: "in 17 days"}
export function formatEventDate(value, now = Date.now()) {
    const date = parseDate(value);
    if (!date) return null;

    const days = daysUntil(date, now);
    let relative;
    if (days === 0) relative = "today";
    else if (days === 1) relative = "tomorrow";
    else if (days === -1) relative = "yesterday";
    else if (days > 1) relative = `in ${days} days`;
    else relative = `${-days} days ago`;

    return {label: formatDay(date, {weekday: "short", month: "short", day: "numeric", year: "numeric"}), relative};
}

// Time left until a manual refresh is allowed: "1 min", "4 min", "1 hr 5 min" (rounded up). null when allowed now
export function formatCountdown(value, now = Date.now()) {
    const date = parseDate(value);
    if (!date) return null;

    const ms = date.getTime() - now;
    if (ms <= 0) return null;

    const minutes = Math.ceil(ms / MINUTE);
    if (minutes < 60) return `${minutes} min`;
    const rest = minutes % 60;
    return rest ? `${Math.floor(minutes / 60)} hr ${rest} min` : `${minutes / 60} hr`;
}

const SENTIMENTS = {
    bullish: {label: "Bullish", className: "bullish"},
    neutral: {label: "Neutral", className: "neutral"},
    bearish: {label: "Bearish", className: "bearish"},
};

export function sentimentMeta(sentiment) {
    return SENTIMENTS[sentiment] ?? null;
}

const CONFIDENCE_LEVELS = {low: 1, medium: 2, high: 3};

// {label: "Medium confidence", level: 2} for the 3-step indicator
export function confidenceMeta(confidence) {
    const level = CONFIDENCE_LEVELS[confidence];
    if (!level) return null;
    return {label: `${confidence[0].toUpperCase()}${confidence.slice(1)} confidence`, level};
}

// tone -> css modifier, anything unexpected is shown as neutral
export function toneClass(tone) {
    return tone === "positive" || tone === "negative" ? tone : "neutral";
}

const ENGINES = {
    rules: {
        label: "Rules-based analysis",
        description: "Written by Zenith's built-in rules from the data shown under “Data behind this analysis”.",
    },
    gemini: {
        label: "AI-written · Gemini",
        description: "Google Gemini reworded the same calculated facts shown under “Data behind this analysis”. "
            + "AI wording can still contain mistakes.",
    },
};

export function engineMeta(engine) {
    return ENGINES[engine] ?? ENGINES.rules;
}

// score -1..1 -> 0..100 position on the gauge; null when there's no usable score
export function scorePosition(score) {
    const n = Number(score);
    if (score === null || score === undefined || !Number.isFinite(n)) return null;
    return ((Math.min(1, Math.max(-1, n)) + 1) / 2) * 100;
}

export function formatScore(score) {
    const n = Number(score);
    if (score === null || score === undefined || !Number.isFinite(n)) return "";
    const clamped = Math.min(1, Math.max(-1, n));
    if (Math.abs(clamped) < 0.005) return "0.00";
    return `${clamped > 0 ? "+" : "−"}${Math.abs(clamped).toFixed(2)}`;
}

const SCENARIO_ORDER = ["bull", "base", "bear"];
const SCENARIO_LABELS = {bull: "Bull case", base: "Base case", bear: "Bear case"};

// Always bull, base, bear (unknown cases dropped) so the colours line up the same way for every asset
export function orderScenarios(scenarios = []) {
    return SCENARIO_ORDER
        .map((name) => scenarios.find((s) => s?.case === name))
        .filter(Boolean)
        .map((scenario) => ({...scenario, label: SCENARIO_LABELS[scenario.case]}));
}

// The 7- and 30-day ranges of a scenario, sorted by horizon, skipping malformed entries
export function scenarioRanges(scenario) {
    const isNumber = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
    return (scenario?.ranges ?? [])
        .filter((r) => isNumber(r?.low) && isNumber(r?.high) && Number(r?.days) > 0)
        .map((r) => {
            const [low, high] = [Number(r.low), Number(r.high)].sort((a, b) => a - b);
            return {days: Number(r.days), low, high};
        })
        .sort((a, b) => a.days - b.days);
}

// % move from the current price, e.g. 95 vs 100 -> -5. null without a usable current price
export function percentFrom(value, base) {
    const v = Number(value);
    const b = Number(base);
    if (!Number.isFinite(v) || !Number.isFinite(b) || b <= 0) return null;
    return ((v - b) / b) * 100;
}

// "−4.8%" / "+12%": short signed percentage for range hints
export function formatShortPercent(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) return "";
    const abs = Math.abs(value);
    if (abs < 0.05) return "0%";
    const digits = abs < 10 ? 1 : 0;
    return `${value > 0 ? "+" : "−"}${abs.toFixed(digits)}%`;
}

const METRIC_GROUPS = [
    ["performance", "Performance"],
    ["trend", "Trend"],
    ["risk", "Risk"],
    ["volume", "Volume"],
    ["fundamentals", "Fundamentals"],
    ["valuation", "Valuation"],
    ["analysts", "Analysts"],
    ["supply", "Supply"],
    ["market", "Market"],
];

// Turn snake_case kinds into a readable label, e.g. "price_level" -> "Price level"
export function humanize(value) {
    const text = String(value ?? "").replace(/_/g, " ").trim();
    return text ? `${text[0].toUpperCase()}${text.slice(1)}` : "";
}

// [{group, label, items}] in a fixed order; groups the backend adds later go at the end
export function groupMetrics(metrics = []) {
    const groups = new Map();
    for (const metric of metrics) {
        if (!metric?.label) continue;
        const key = metric.group || "other";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(metric);
    }

    const known = METRIC_GROUPS.filter(([key]) => groups.has(key)).map(([key, label]) => ({
        group: key, label, items: groups.get(key),
    }));
    const extra = [...groups.keys()]
        .filter((key) => !METRIC_GROUPS.some(([k]) => k === key))
        .map((key) => ({group: key, label: humanize(key), items: groups.get(key)}));
    return [...known, ...extra];
}

// Only http(s) links from the API become clickable
export function safeUrl(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
    } catch {
        return null;
    }
}

// Identifies the asset a report belongs to. A response is only shown when its key matches the selected asset
export function analystRequestKey({symbol, type, coinId}) {
    return [type ?? "", symbol ?? "", coinId ?? ""].join("|");
}

// Keeps track of the newest request. Starting a new one aborts the previous one, and isCurrent() tells a late
// response (one that ignored the abort) that it has been replaced
export function createLatestRequestTracker() {
    let counter = 0;
    let current = null;

    return {
        start() {
            current?.controller.abort();
            const controller = new AbortController();
            const id = ++counter;
            current = {id, controller};
            return {id, signal: controller.signal, isCurrent: () => current?.id === id};
        },
        cancel() {
            current?.controller.abort();
            current = null;
        },
    };
}

// Run `fetcher(signal)` as the newest request of `tracker`.
// Resolves to {status: "ok", data}, {status: "error", error} or {status: "superseded"} when a newer request
// (or cancel) replaced it; superseded results must be ignored
export async function fetchLatest(tracker, fetcher) {
    const req = tracker.start();
    try {
        const data = await fetcher(req.signal);
        return req.isCurrent() ? {status: "ok", data} : {status: "superseded"};
    } catch (error) {
        if (!req.isCurrent() || error?.name === "AbortError") return {status: "superseded"};
        return {status: "error", error};
    }
}
