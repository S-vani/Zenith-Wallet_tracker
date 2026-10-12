const formatters = {};

export const SUPPORTED_CURRENCIES = ["CAD", "USD", "EUR"];

// Older accounts can have an empty or unexpected currency saved, which makes Intl throw "Invalid currency code"
export function normalizeCurrency(currency) {
    const code = String(currency ?? "").trim().toUpperCase();
    return SUPPORTED_CURRENCIES.includes(code) ? code : "CAD";
}

// Format a number as money in the users currency, e.g. 1234.5 -> "$1,234.50" / "€1,234.50"
export function formatMoney(value, currency = "CAD", options = {}) {
    currency = normalizeCurrency(currency);
    const key = `${currency}-${JSON.stringify(options)}`;

    if (!formatters[key]) {
        formatters[key] = new Intl.NumberFormat(undefined, {
            style: "currency",
            currency,
            // "symbol" shows CA$ / US$ when it isn't the reader's local dollar, so CAD and USD can be told apart
            currencyDisplay: "symbol",
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
            ...options,
        });
    }

    const n = Number(value) || 0;

    // absurdly large numbers would overflow every card, so switch to compact notation (e.g. $1.2T)
    if (Math.abs(n) >= 1e12 && !options.notation) {
        return formatMoney(n, currency, {notation: "compact", maximumFractionDigits: 1, minimumFractionDigits: 0});
    }

    return formatters[key].format(n);
}

// Money with an explicit sign, used for gains and losses
export function formatSignedMoney(value, currency = "CAD") {
    let n = Number(value) || 0;
    if (Math.abs(n) < 0.005) n = 0; // would round to $0.00, so don't show a sign
    return `${n > 0 ? "+" : n < 0 ? "−" : ""}${formatMoney(Math.abs(n), currency)}`;
}

export function formatPercent(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    if (Math.abs(n) < 0.005) return "0.00%";
    return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(2)}%`;
}

// Quantities can be fractional (crypto), so show up to 8 decimals without float noise
export function formatQuantity(value) {
    const n = Number(value);
    if (Math.abs(n) >= 1e12) return n.toLocaleString(undefined, {notation: "compact", maximumFractionDigits: 1});
    return n.toLocaleString(undefined, {maximumFractionDigits: 8});
}

export function changeClass(value) {
    const n = Number(value);
    if (n > 0) return "positive";
    if (n < 0) return "negative";
    return "neutral";
}
