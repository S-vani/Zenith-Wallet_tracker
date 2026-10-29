// Pure helpers shared by the add and edit trade forms and the trade details (tested in test/tradeForm.test.js and
// test/transactions-helpers.test.js)

import {formatMoney, formatPrice} from "../utils/format.js";
import {ACCOUNT_UNSET, accountLabel, normalizeAccountType} from "../utils/accounts.js";

// Two digits ("05").
const pad = (n) => String(n).padStart(2, "0");

// A Date as the "YYYY-MM-DDTHH:MM" local time a datetime-local input shows
export function toLocalInputValue(date) {
    const d = new Date(date);
    if (Number.isNaN(d.getTime())) return "";
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// A datetime-local value has no time zone and JS reads it as local time, so this is the user's local time in UTC
// (the same way the date filters send their start/end of day). The backend stores it as naive UTC.
export function localInputToIso(value) {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// Whether a datetime-local value is later than now (with a little slack for a fast clock).
export function isFutureInput(value, now = new Date()) {
    if (!value) return false;
    const d = new Date(value);
    return !Number.isNaN(d.getTime()) && d > now;
}

// The quantity and price fields are plain text with a decimal keypad: iPhones set to French, German etc. only offer
// a comma there, and a type="number" field silently turns "1,5" into "". So "1,5" and "1.5" both mean 1.5. A second
// separator ("1,234.5", "1.234,5"), letters or exponents are rejected rather than guessed. Returns NaN when invalid.
const DECIMAL_TEXT = /^(\d+([.,]\d*)?|[.,]\d+)$/;

// A typed amount as a number: "1,5" and "1.5" both work; null for anything else.
export function parseDecimalInput(text) {
    const value = String(text ?? "").trim();
    if (!DECIMAL_TEXT.test(value)) return NaN;
    return Number(value.replace(",", "."));
}

// What's wrong with the typed quantity/price, or null. Empty fields aren't flagged yet (Save just stays disabled).
export function amountHint(quantity, price) {
    const typed = [quantity, price].filter((v) => String(v ?? "").trim() !== "");
    if (typed.some((v) => Number.isNaN(parseDecimalInput(v)))) {
        return "Enter numbers only, like 1.5 or 1,5 (no thousands separators).";
    }
    if (typed.some((v) => !(parseDecimalInput(v) > 0))) return "Quantity and price must both be greater than 0.";
    return null;
}

// A quantity as plain text for the input: String(0.0000001) is "1e-7", which the field wouldn't accept back.
// Quantities are stored with 10 decimals, so that's all that's kept. The shortest form of the rounded number is
// used where it has no exponent: toFixed(10) alone wrote binary noise for big ones ("1234567.1000000001").
export function quantityInputValue(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return "";
    const rounded = Number(n.toFixed(10));
    const shortest = String(rounded);
    if (!/e/i.test(shortest)) return shortest;
    return rounded.toFixed(10).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

// What the add-trade form starts from when a search result is picked. The coin's CoinGecko id has to come along:
// several coins share a ticker, and without it the trade (and its price and chart) would use the most popular one.
export function symbolSelection(result) {
    return {
        api_id: result.api_id,
        symbol: result.symbol,
        type: result.type,
        price: result.price,
        ...(result.type === "crypto" && result.coin_id ? {coin_id: result.coin_id} : {}),
    };
}

// Body for POST /transactions. The date is only sent when the user changed it, so an untouched form is dated
// "now" by the server at the moment it's saved. A coin also sends its CoinGecko id from search, since several
// coins can share a ticker and the server would otherwise price the most popular one. The account is only sent
// when one is picked ("Not set" = left out, which the server stores as null).
export function createPayload(form, initialDate) {
    const changedDate = form.created_at && form.created_at !== initialDate;
    const coinId = form.asset_type === "crypto" && form.coin_id ? form.coin_id : null;
    const account = normalizeAccountType(form.account_type);
    return {
        symbol: form.symbol,
        api_id: form.api_id,
        asset_type: form.asset_type,
        action: form.action,
        quantity: parseDecimalInput(form.quantity),
        price_of_one: parseDecimalInput(form.price_of_one),
        ...(coinId ? {coin_id: coinId} : {}),
        ...(account ? {account_type: account} : {}),
        ...(changedDate ? {created_at: localInputToIso(form.created_at)} : {}),
    };
}

// Body for PUT /transactions/{id}: only what changed. Re-sending an unchanged price would make the server convert it
// again (at the trade date's rate, or today's when that isn't available), and re-sending the date would drop its seconds.
export function updatePayload(initial, form) {
    const changes = {};
    if (form.action !== initial.action) changes.action = form.action;
    if (form.quantity !== initial.quantity) changes.quantity = parseDecimalInput(form.quantity);
    if (form.price_of_one !== initial.price_of_one) changes.price_of_one = parseDecimalInput(form.price_of_one);
    if (form.created_at && form.created_at !== initial.created_at) {
        changes.created_at = localInputToIso(form.created_at);
    }
    // null clears it on the server (switching to "Not set")
    const account = normalizeAccountType(form.account_type);
    if (account !== normalizeAccountType(initial.account_type)) changes.account_type = account;
    return changes;
}

// The 409 detail when a sell would take more than its own account held (see account_split in the backend)
export const ACCOUNT_OVERSOLD = "Insufficient holdings in that account";

// How much a sell from `account` can take, for the add form's "You own N" hint. Same rule as the server: a sell
// tagged with an account may use that account's shares plus the "not set" ones (they could be in any account),
// never more than the whole holding; a sell with no account set is only checked against the whole holding.
// `holding` is a /holdings row (its `accounts` is {account or "UNSET": quantity}); null = none held.
export function ownedForAccount(holding, account) {
    if (!holding) return {owned: 0, inAccount: null};
    const total = Number(holding.quantity) || 0;
    const acct = normalizeAccountType(account);
    if (!acct || !holding.accounts) return {owned: total, inAccount: null};
    const own = Number(holding.accounts[acct]) || 0;
    const unset = Number(holding.accounts[ACCOUNT_UNSET]) || 0;
    return {owned: Math.min(total, own + unset), inAccount: acct};
}

// " in TFSA" after "You own 3 AAPL", nothing when the hint covers every account
export function accountSuffix(inAccount) {
    return inAccount ? ` in ${accountLabel(inAccount)}` : "";
}

// The backend answers 409 when a save, edit or delete would make the history sell more than was owned at some
// point. Say what that means for the thing the user just tried.
export function ledgerErrorMessage(err, {mode, symbol = "", action = "BUY", backdated = false} = {}) {
    if (err?.status !== 409) return err?.message ?? "Something went wrong. Please try again.";
    const name = symbol.toUpperCase();

    if (err.message === ACCOUNT_OVERSOLD) {
        if (mode === "delete") {
            return `This buy can't be deleted: a later sell of ${name} from the same account needs it.`;
        }
        if (mode === "edit") {
            return `That change would leave a sell of ${name} taking more than its account held at the time. ` +
                "Check the account, quantity and date.";
        }
        return `That account didn't hold that much ${name}${backdated ? " on that date" : ""}. Check the account ` +
            "you picked (shares with no account set count for any account).";
    }

    if (mode === "delete") {
        return `This buy can't be deleted: a later sell of ${name} needs it. Delete or edit that sell first.`;
    }
    if (mode === "edit") {
        return `That change would leave your ${name} history selling more than you owned at the time. ` +
            "Check the quantity and date, and any sells after it.";
    }
    if (action === "SELL" && backdated) {
        return `You didn't own that much ${name} on that date (or it would leave a later sell short).`;
    }
    if (action === "SELL") return `You can't sell more ${name} than you own.`;
    return `Saving this would leave your ${name} history selling more than you owned at the time.`;
}

// The add form prefills the current price. Once the user moves the date to another day and leaves that price
// untouched, it's almost certainly not what they paid then (we don't look up old prices), so say so.
export function backdatedPriceHint(form, initialDate, prefilledPrice) {
    if (!prefilledPrice || form.price_of_one !== prefilledPrice) return null;
    if (!form.created_at || form.created_at.slice(0, 10) === String(initialDate ?? "").slice(0, 10)) return null;
    const date = new Date(form.created_at);
    if (Number.isNaN(date.getTime())) return null;
    const day = date.toLocaleString(undefined, {month: "short", day: "numeric", year: "numeric"});
    const what = form.action === "SELL" ? "what you sold for" : "what you paid";
    return `This is the current price — enter ${what} on ${day}.`;
}

// formatMoney shortens amounts from 1e12 ("CA$97.5T") so they fit rows and cards; the expanded trade details have
// room for the exact figure, which is what opening them is for.
export function fullMoney(value, currency) {
    return formatMoney(value, currency, {notation: "standard"});
}

// A unit price as text, in full when it's huge.
export function fullPrice(value, currency) {
    return Math.abs(Number(value)) >= 1e12 ? fullMoney(value, currency) : formatPrice(value, currency);
}

// A signed amount as text, in full when it's huge.
export function fullSignedMoney(value, currency) {
    if (currency === null) return fullMoney(value, currency); // "—", not "+—"
    let n = Number(value) || 0;
    if (Math.abs(n) < 0.005) n = 0; // would round to $0.00, so don't show a sign
    return `${n > 0 ? "+" : n < 0 ? "−" : ""}${fullMoney(Math.abs(n), currency)}`;
}
