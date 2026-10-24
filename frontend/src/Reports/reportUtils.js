// Pure helpers for the capital gains page (tested in test/reports-utils.test.js). Tax is reported in CAD, so every
// amount here is formatted in CAD whatever the user's display currency is.
import {formatMoney, formatSignedMoney} from "../utils/format.js";

export const REPORT_CURRENCY = "CAD";

export function cad(value) {
    return formatMoney(value, REPORT_CURRENCY);
}

export function signedCad(value) {
    return formatSignedMoney(value, REPORT_CURRENCY);
}

// The year to show first: the one asked for if it has sales, else the newest. null when there are none.
export function pickYear(years, wanted) {
    if (!Array.isArray(years) || years.length === 0) return null;
    const n = Number(wanted);
    return years.includes(n) ? n : years[0];
}

// The short labels shown on a sale (the server's notes say the details). Order = how much it matters.
export function saleFlags(sale) {
    const flags = [];
    if (sale?.oversold) flags.push({kind: "oversold", label: "Check account types"});
    if (sale?.superficial_loss) flags.push({kind: "superficial", label: "Possible superficial loss"});
    if (sale?.foreign_currency) flags.push({kind: "foreign", label: "Foreign currency"});
    return flags;
}

// "Shares", "coins" etc. aren't known for every asset, so the label only names the security
export function securityLabel(sale) {
    const type = sale?.asset_type === "crypto" ? "Crypto" : "Stock";
    return `${sale?.symbol ?? ""} · ${type}`;
}

// The informational inclusion-rate line under the totals
export function inclusionLine(totals) {
    const net = Number(totals?.net) || 0;
    if (net > 0) {
        return `50% of a net capital gain is taxable: ${cad(totals.taxable_at_50pct)} of ${cad(net)}.`;
    }
    if (net < 0) {
        return "A net capital loss isn't taxable. CRA lets you carry it back 3 years or forward to reduce "
            + "capital gains in other years.";
    }
    return "No net capital gain this year.";
}

// How many sales carry each warning, for the summary above the table
export function warningCounts(sales) {
    const counts = {oversold: 0, superficial: 0, foreign: 0};
    for (const sale of sales ?? []) {
        for (const {kind} of saleFlags(sale)) counts[kind] += 1;
    }
    return counts;
}

export function plural(count, word, many = `${word}s`) {
    return `${count} ${count === 1 ? word : many}`;
}
