// The Transactions filter system, as pure functions (tested in test/filterModel.test.js). The page loads every trade
// once and filters here, so chips react at once, counts are always right and filtering works offline in the app.
//
// A filter set: {q, actions: ["BUY"|"SELL"], kinds: ["stock"|"crypto"], accounts: [type | "UNSET"], from, to, min, max}
// Several values in one group are OR ("Buy" or "Sell"); different groups are AND. Dates are "YYYY-MM-DD" in the
// user's own calendar, amounts are in the user's currency (price x quantity, as the list shows them).

export const EMPTY_FILTERS = {q: "", actions: [], kinds: [], accounts: [], from: "", to: "", min: "", max: ""};

const GROUPS = ["actions", "kinds", "accounts"];
const ACCOUNT_WORDS = {
    tfsa: "TFSA", rrsp: "RRSP", fhsa: "FHSA", resp: "RESP",
    nonreg: "NON_REGISTERED", "non-registered": "NON_REGISTERED", unregistered: "NON_REGISTERED",
};

const pad = (n) => String(n).padStart(2, "0");

// "YYYY-MM-DD" of a Date in local time.
export function dayString(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// The trade's day (its local calendar date), or "" when the timestamp is unreadable. Stored as naive UTC, so a
// timestamp without an offset is read as UTC.
export function tradeDay(trade) {
    const raw = String(trade.created_at ?? "");
    const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`);
    return Number.isNaN(date.getTime()) ? "" : dayString(date);
}

// A trade's total in the user's currency.
export function tradeAmount(trade) {
    return Math.abs(Number(trade.price_of_one) * Number(trade.quantity)) || 0;
}

const accountOf = (trade) => trade.account_type || "UNSET";

function numberOrNull(value) {
    if (value === "" || value === null || value === undefined) return null;
    const n = Number(String(value).replace(",", "."));
    return Number.isFinite(n) ? n : null;
}

const CHECKS = {
    q: (t, f) => !f.q.trim() || String(t.symbol ?? "").toLowerCase().includes(f.q.trim().toLowerCase()),
    actions: (t, f) => !f.actions.length || f.actions.includes(t.action),
    kinds: (t, f) => !f.kinds.length || f.kinds.includes(t.asset_type),
    accounts: (t, f) => !f.accounts.length || f.accounts.includes(accountOf(t)),
    dates: (t, f) => {
        if (!f.from && !f.to) return true;
        const day = tradeDay(t);
        return day !== "" && (!f.from || day >= f.from) && (!f.to || day <= f.to);
    },
    amount: (t, f) => {
        const min = numberOrNull(f.min);
        const max = numberOrNull(f.max);
        if (min === null && max === null) return true;
        const total = tradeAmount(t);
        return (min === null || total >= min) && (max === null || total <= max);
    },
};

// The trades that pass every group except `skip` (used to count what a chip WOULD give).
export function applyFilters(trades, filters, skip = null) {
    const checks = Object.entries(CHECKS).filter(([name]) => name !== skip);
    return trades.filter((t) => checks.every(([, check]) => check(t, filters)));
}

// How many trades each chip would show if it were switched on, given the other groups:
// {actions: {BUY: n, SELL: n}, kinds: {stock: n, crypto: n}, accounts: {TFSA: n, ..., UNSET: n}}
export function facetCounts(trades, filters) {
    const counts = {actions: {}, kinds: {}, accounts: {}};
    const field = {actions: (t) => t.action, kinds: (t) => t.asset_type, accounts: accountOf};
    for (const group of GROUPS) {
        for (const t of applyFilters(trades, filters, group)) {
            const key = field[group](t);
            if (key) counts[group][key] = (counts[group][key] ?? 0) + 1;
        }
    }
    return counts;
}

// The account types that appear in the trades (so the chips never list an account with nothing in it), in a stable
// order, "not set" last.
export function accountsPresent(trades, order) {
    const seen = new Set(trades.map(accountOf));
    return [...order.filter((a) => seen.has(a)), ...(seen.has("UNSET") ? ["UNSET"] : [])];
}

// The answer a filtered list gives: how many trades, what was bought and what was sold (user's currency).
export function summarize(trades) {
    let bought = 0;
    let sold = 0;
    for (const t of trades) {
        if (t.action === "BUY") bought += tradeAmount(t);
        else if (t.action === "SELL") sold += tradeAmount(t);
    }
    return {count: trades.length, bought, sold};
}

// How many filters are on (each chip, each date end, each amount end and the text count one).
export function activeCount(f) {
    return (f.q.trim() ? 1 : 0) + f.actions.length + f.kinds.length + f.accounts.length
        + (f.from ? 1 : 0) + (f.to ? 1 : 0) + (numberOrNull(f.min) !== null ? 1 : 0) + (numberOrNull(f.max) !== null ? 1 : 0);
}

// Switches one value in a group on or off.
export function toggleValue(filters, group, value) {
    const list = filters[group];
    return {...filters, [group]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value]};
}

// ---- date presets: "Last 30 days", "This year", "Last year" -> {id, label, from, to}
export function datePresets(now = new Date()) {
    const year = now.getFullYear();
    const back = new Date(now);
    back.setDate(back.getDate() - 29);
    return [
        {id: "30d", label: "Last 30 days", from: dayString(back), to: dayString(now)},
        {id: "ytd", label: "This year", from: `${year}-01-01`, to: `${year}-12-31`},
        {id: "ly", label: "Last year", from: `${year - 1}-01-01`, to: `${year - 1}-12-31`},
    ];
}

// The preset the current dates match, or null.
export function activePreset(filters, now = new Date()) {
    return datePresets(now).find((p) => p.from === filters.from && p.to === filters.to) ?? null;
}

// ---- the search bar: recognised words become chips, the rest is matched against the symbol
// "buy", "sell", "stock(s)", "crypto", "tfsa"..., "2026", ">500", "<2000", "last 30d". Returns the new filters and
// the text that wasn't recognised (the caller leaves that in the box).
export function absorbText(filters, text, now = new Date()) {
    let next = {...filters, actions: [...filters.actions], kinds: [...filters.kinds], accounts: [...filters.accounts]};
    let rest = String(text);

    const last = rest.match(/\blast\s+(\d{1,4})\s*d(?:ays?)?\b/i);
    if (last) {
        const from = new Date(now);
        from.setDate(from.getDate() - (Number(last[1]) - 1));
        next = {...next, from: dayString(from), to: dayString(now)};
        rest = rest.replace(last[0], " ");
    }

    const words = rest.split(/\s+/).filter(Boolean);
    const unknown = [];
    for (const word of words) {
        const w = word.toLowerCase();
        if (w === "buy" || w === "buys" || w === "bought") next = withValue(next, "actions", "BUY");
        else if (w === "sell" || w === "sells" || w === "sold") next = withValue(next, "actions", "SELL");
        else if (w === "stock" || w === "stocks" || w === "etf" || w === "etfs") next = withValue(next, "kinds", "stock");
        else if (w === "crypto" || w === "coin" || w === "coins") next = withValue(next, "kinds", "crypto");
        else if (ACCOUNT_WORDS[w]) next = withValue(next, "accounts", ACCOUNT_WORDS[w]);
        else if (/^(19|20)\d\d$/.test(w)) next = {...next, from: `${w}-01-01`, to: `${w}-12-31`};
        else if (/^>\d+([.,]\d+)?$/.test(w)) next = {...next, min: w.slice(1).replace(",", ".")};
        else if (/^<\d+([.,]\d+)?$/.test(w)) next = {...next, max: w.slice(1).replace(",", ".")};
        else unknown.push(word);
    }
    return {filters: next, rest: unknown.join(" ")};
}

function withValue(filters, group, value) {
    return filters[group].includes(value) ? filters : {...filters, [group]: [...filters[group], value]};
}

// ---- the address: ?action=BUY&kind=stock&acct=TFSA,UNSET&from=2026-01-01&to=...&min=&max=&q=&sort=
const ACTIONS = new Set(["BUY", "SELL"]);
const KINDS = new Set(["stock", "crypto"]);
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function filtersToSearch(filters, sort = "newest") {
    const p = new URLSearchParams();
    if (filters.q.trim()) p.set("q", filters.q.trim());
    if (filters.actions.length) p.set("action", filters.actions.join(","));
    if (filters.kinds.length) p.set("kind", filters.kinds.join(","));
    if (filters.accounts.length) p.set("acct", filters.accounts.join(","));
    if (filters.from) p.set("from", filters.from);
    if (filters.to) p.set("to", filters.to);
    if (numberOrNull(filters.min) !== null) p.set("min", String(filters.min));
    if (numberOrNull(filters.max) !== null) p.set("max", String(filters.max));
    if (sort && sort !== "newest") p.set("sort", sort);
    return p.toString();
}

// Reads the address back. Anything unexpected is dropped, never trusted (the address can be edited by anyone).
export function filtersFromSearch(search, allowedAccounts = []) {
    const p = new URLSearchParams(search);
    const list = (key, ok) => (p.get(key) ?? "").split(",").filter((v, i, all) => ok(v) && all.indexOf(v) === i);
    const accounts = new Set([...allowedAccounts, "UNSET"]);
    const day = (key) => (DAY.test(p.get(key) ?? "") ? p.get(key) : "");
    const amount = (key) => (numberOrNull(p.get(key)) !== null && numberOrNull(p.get(key)) >= 0 ? p.get(key) : "");
    return {
        filters: {
            q: (p.get("q") ?? "").slice(0, 40),
            actions: list("action", (v) => ACTIONS.has(v)),
            kinds: list("kind", (v) => KINDS.has(v)),
            accounts: list("acct", (v) => accounts.has(v)),
            from: day("from"),
            to: day("to"),
            min: amount("min"),
            max: amount("max"),
        },
        sort: p.get("sort") ?? "newest",
    };
}

// ---- pills under the bar: what is on, each with how to switch it off
export function activePills(filters, labelFor) {
    const pills = [];
    if (filters.q.trim()) pills.push({key: "q", label: `Symbol: ${filters.q.trim()}`, off: (f) => ({...f, q: ""})});
    for (const group of GROUPS) {
        for (const value of filters[group]) {
            pills.push({
                key: `${group}:${value}`, label: labelFor(group, value),
                off: (f) => ({...f, [group]: f[group].filter((v) => v !== value)}),
            });
        }
    }
    if (filters.from || filters.to) {
        const label = filters.from && filters.to ? `${filters.from} → ${filters.to}`
            : filters.from ? `From ${filters.from}` : `Until ${filters.to}`;
        pills.push({key: "dates", label, off: (f) => ({...f, from: "", to: ""})});
    }
    if (numberOrNull(filters.min) !== null || numberOrNull(filters.max) !== null) {
        const lo = numberOrNull(filters.min);
        const hi = numberOrNull(filters.max);
        const label = lo !== null && hi !== null ? `Amount ${lo}–${hi}` : lo !== null ? `Amount over ${lo}` : `Amount under ${hi}`;
        pills.push({key: "amount", label, off: (f) => ({...f, min: "", max: ""})});
    }
    return pills;
}

// For an empty result: the single pill whose removal brings back the most trades, or null.
export function bestRelaxation(trades, filters, labelFor) {
    let best = null;
    for (const pill of activePills(filters, labelFor)) {
        const count = applyFilters(trades, pill.off(filters)).length;
        if (count > 0 && (!best || count > best.count)) best = {pill, count};
    }
    return best;
}
