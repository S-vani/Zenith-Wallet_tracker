const formatters = {};

export const SUPPORTED_CURRENCIES = ["CAD", "USD", "EUR"];

// Older accounts can have an empty or unexpected currency saved, which makes Intl throw "Invalid currency code"
export function normalizeCurrency(currency) {
    const code = String(currency ?? "").trim().toUpperCase();
    return SUPPORTED_CURRENCIES.includes(code) ? code : "CAD";
}

// The user context's currency is null until /user has loaded: show "—" rather than a guessed CA$ label
export const UNKNOWN_MONEY = "—";

// Format a number as money in the users currency, e.g. 1234.5 -> "$1,234.50" / "€1,234.50"
export function formatMoney(value, currency = "CAD", options = {}) {
    if (currency === null) return UNKNOWN_MONEY;
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

    // In a US locale Intl writes USD as a bare "$", which Canadians (the app's main users) read as CA$. Spell it
    // "US$" so the user's USD amounts can't be mistaken for Canadian dollars. CAD keeps Intl's own symbol.
    if (currency === "USD") {
        return formatters[key].formatToParts(n)
            .map((part) => (part.type === "currency" && part.value === "$" ? "US$" : part.value))
            .join("");
    }
    return formatters[key].format(n);
}

// Decimals needed to show a price meaningfully: 2 for normal prices, more for sub-dollar coins
function priceDecimals(value) {
    const n = Math.abs(Number(value));
    if (!n || n >= 1) return 2;
    // keep about 4 significant digits, e.g. 0.1234, 0.0006481, 0.0000000005438
    return Math.min(20, Math.max(2, Math.ceil(-Math.log10(n)) + 3));
}

// A single asset price: "$1,234.56", "$0.000648", "$0.0000000005438" (never "$0.00" for a real price)
export function formatPrice(value, currency = "CAD") {
    const decimals = priceDecimals(value);
    return formatMoney(value, currency, {minimumFractionDigits: 2, maximumFractionDigits: decimals});
}

// Plain number string for prefilling a price input, without float noise or exponents
export function priceInputValue(value) {
    const n = Number(value);
    if (!(n > 0)) return "";
    return n.toFixed(priceDecimals(n)).replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
}

// Money with an explicit sign, used for gains and losses
export function formatSignedMoney(value, currency = "CAD") {
    if (currency === null) return UNKNOWN_MONEY; // no "+—"
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

// The line under a search result's ticker: "TSX · Shopify Inc." vs "NYSE · Shopify Inc.", so the US and Canadian
// listings of one company can be told apart. The exchange goes first so a long name is what gets cut off.
export function listingName(result) {
    const name = result?.name ?? "";
    const exchange = result?.type === "stock" ? result?.exchange : "";
    return [exchange, name].filter(Boolean).join(" · ");
}

export function changeClass(value) {
    const n = Number(value);
    if (n > 0) return "positive";
    if (n < 0) return "negative";
    return "neutral";
}
