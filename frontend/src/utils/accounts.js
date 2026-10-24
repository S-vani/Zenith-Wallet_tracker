// The account a trade was made in (tested in test/accounts.test.js). Same values as ACCOUNT_TYPES in
// backend/schemas/assets.py; null = not set (older trades, people who don't track accounts).
export const ACCOUNT_TYPES = [
    {value: "TFSA", label: "TFSA"},
    {value: "RRSP", label: "RRSP"},
    {value: "FHSA", label: "FHSA"},
    {value: "RESP", label: "RESP"},
    {value: "NON_REGISTERED", label: "Non-registered"},
];

// GET /transactions?account_type=UNSET lists the trades with no account set
export const ACCOUNT_UNSET = "UNSET";

const LABELS = new Map(ACCOUNT_TYPES.map(({value, label}) => [value, label]));

export function isAccountType(value) {
    return LABELS.has(value);
}

// One of the values, or null for anything else ("" from the "Not set" option, a stale saved value...)
export function normalizeAccountType(value) {
    return isAccountType(value) ? value : null;
}

// "Non-registered" for NON_REGISTERED, "—" when not set. A value this version doesn't know (a newer server) is
// shown as sent rather than hidden.
export function accountLabel(value) {
    if (value === null || value === undefined || value === "") return "—";
    return LABELS.get(value) ?? String(value);
}

// People usually log a batch of trades from one account, so the add form starts on the last one picked in this
// browser. Storage can be missing or throw (private mode, blocked site data); then it simply starts on "Not set".
const LAST_ACCOUNT_KEY = "lastAccountType";

function storage() {
    try {
        return globalThis.localStorage ?? null;
    } catch {
        return null;
    }
}

export function loadLastAccount() {
    try {
        return normalizeAccountType(storage()?.getItem(LAST_ACCOUNT_KEY));
    } catch {
        return null;
    }
}

export function saveLastAccount(value) {
    try {
        const account = normalizeAccountType(value);
        if (account) storage()?.setItem(LAST_ACCOUNT_KEY, account);
        else storage()?.removeItem(LAST_ACCOUNT_KEY);
    } catch {
        // not remembered; the form still works
    }
}

// on sign out, so the next person using this browser doesn't start on someone else's account
export function forgetLastAccount() {
    saveLastAccount(null);
}
