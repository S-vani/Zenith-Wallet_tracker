// Pure helpers for the dashboard's Allocation card (tested in test/allocation-data.test.js)
import {formatMoney} from "../utils/format.js";
import {accountLabel} from "../utils/accounts.js";

// Slice colours, all from colours the app already uses (Global.css tokens and the alert / chart colours), picked to
// stay apart from each other on the navy cards. The legend always names each slice, so nothing relies on colour.
export const ALLOCATION_COLORS = [
    "#3b82f6", // --accent
    "#f59e0b", // warning amber
    "#22c55e", // --positive
    "#c4b5fd", // violet
    "#f87171", // alert red
    "#93c5fd", // --accent-soft
    "#fcd34d", // warning text
    "#cbd5e1", // light slate
];
// "Other" is a mix of everything left, so it gets a neutral grey instead of a colour of its own
export const OTHER_COLOR = "#6b7790";

export const TOP_HOLDINGS = 8; // after this many, the rest of the holdings are one "Other" slice

export const OTHER_KEY = "__other__";

// The card's tabs: which list of the /portfolio/allocation reply each one shows
export const ALLOCATION_VIEWS = [
    {value: "asset_type", label: "Asset type", field: "by_asset_type", title: "by asset type"},
    {value: "account", label: "Account", field: "by_account", title: "by account"},
    {value: "holding", label: "Holdings", field: "by_holding", title: "by holding"},
    {value: "currency", label: "Currency", field: "by_currency", title: "by listing currency"},
];

const ASSET_TYPE_LABELS = {stock: "Stocks", crypto: "Crypto"};
const CURRENCY_LABELS = {CRYPTO: "Crypto", OTHER: "Other"};

// Only the views the server sent: a server without the currency group simply doesn't get that tab
export function availableViews(data) {
    return ALLOCATION_VIEWS.filter(({field}) => Array.isArray(data?.[field]));
}

export function sliceLabel(view, key) {
    if (view === "asset_type") return ASSET_TYPE_LABELS[key] ?? String(key);
    if (view === "account") return key === "UNSET" ? "Not set" : accountLabel(key);
    if (view === "currency") return CURRENCY_LABELS[key] ?? String(key);
    return String(key).toUpperCase(); // holdings: tickers are shown in capitals everywhere else
}

// The top `n` rows as they are and the rest added up into one "Other" row, so there are never more slices than
// distinct colours
export function groupTopN(rows, n = TOP_HOLDINGS) {
    const list = rows ?? [];
    if (list.length <= n) return list;
    const rest = list.slice(n);
    return [
        ...list.slice(0, n),
        {
            key: OTHER_KEY,
            label: `Other (${rest.length})`,
            value: rest.reduce((sum, r) => sum + (Number(r.value) || 0), 0),
            weight: rest.reduce((sum, r) => sum + (Number(r.weight) || 0), 0),
            count: rest.length,
        },
    ];
}

// One view's rows ready to draw: {key, label, value, weight, color}, largest first, at most the top 8 + "Other"
export function allocationRows(data, view) {
    const info = ALLOCATION_VIEWS.find((v) => v.value === view);
    const raw = (info && data?.[info.field]) || [];
    const rows = raw
        .map((r) => {
            const key = view === "holding" ? `${r.asset_type}:${r.symbol}` : r.key;
            const name = view === "holding" ? r.symbol : r.key;
            return {key, label: sliceLabel(view, name), value: Number(r.value) || 0, weight: Number(r.weight) || 0};
        })
        .filter((r) => r.value > 0);
    const shown = groupTopN(rows); // mostly holdings; a portfolio can also span many listing currencies
    let colour = 0;
    return shown.map((r) => ({
        ...r,
        color: r.key === OTHER_KEY ? OTHER_COLOR : ALLOCATION_COLORS[colour++ % ALLOCATION_COLORS.length],
    }));
}

// A weight (0-1) as a share: "45.2%", "<0.1%" for a sliver that would otherwise read as nothing, "—" if unknown
export function formatWeight(weight) {
    const n = Number(weight);
    if (weight === null || weight === undefined || !Number.isFinite(n)) return "—";
    const pct = n * 100;
    if (pct > 0 && pct < 0.05) return "<0.1%";
    return `${pct.toFixed(1)}%`;
}

// What a screen reader gets instead of the donut, e.g. "Allocation by account: TFSA 60.0% (CA$600.00), RRSP 40.0%
// (CA$400.00)."
export function allocationSummary(rows, view, currency) {
    const title = ALLOCATION_VIEWS.find((v) => v.value === view)?.title ?? "";
    const heading = `Allocation ${title}`.trim();
    if (!rows || rows.length === 0) return `${heading}: no priced holdings.`;
    const parts = rows.map((r) => `${r.label} ${formatWeight(r.weight)} (${formatMoney(r.value, currency)})`);
    return `${heading}: ${parts.join(", ")}.`;
}
