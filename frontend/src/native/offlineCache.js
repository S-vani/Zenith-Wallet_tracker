import {isNative} from "./platform.js";

// App only: the last successful response of the portfolio screens is kept on the phone, so they still show data
// (under the "You're offline" banner) without a connection, even right after opening the app.
// The website never stores portfolio data in the browser. Cleared on sign out and account deletion.
//
// Entries belong to one user *and* one currency (the server converts every amount to the user's currency), so a
// currency change or another account never shows numbers saved for someone or something else. The scope comes
// from the user's own profile (/user, or the reply to saving it) and is kept so a cold start offline finds it.
const PREFIX = "offline:";
const SCOPE_KEY = "offline-scope";
const INDEX_KEY = "offline-index"; // least recently used first
const MAX_ENTRIES = 40;
const CACHED = ["/dashboard", "/portfolio/history", "/holdings", "/transactions", "/user", "/prices/history"];
// screens with endless variants (every chart range of every symbol, every filter) keep only their latest few
const LIMITS = {"/prices/history": 8, "/transactions": 5};
const USER_PATHS = ["/user", "/user/information"]; // replies that are the user's profile

const base = (path) => path.split("?")[0];
const cacheable = (path) => CACHED.includes(base(path));

// Bumped by forgetAll(): a request that started before a sign out must not save the previous user's data after it
let generation = 0;

function storage() {
    try {
        return isNative ? globalThis.localStorage ?? null : null;
    } catch {
        return null;
    }
}

function readJson(key, fallback) {
    try {
        const saved = storage()?.getItem(key);
        return saved == null ? fallback : JSON.parse(saved);
    } catch {
        return fallback;
    }
}

function currentScope() {
    return readJson(SCOPE_KEY, null);
}

const keyFor = (scope, path) => `${PREFIX}${scope}:${path}`;

function saveIndex(index) {
    storage()?.setItem(INDEX_KEY, JSON.stringify(index));
}

const pathOf = (key) => key.slice(key.indexOf(":/") + 1); // "offline:<id>:<currency>:/path?query" -> "/path?query"

// moves key to the most recently used end and evicts beyond the limits
function touch(key, path) {
    const store = storage();
    let index = readJson(INDEX_KEY, []).filter((k) => k !== key);
    index.push(key);
    const evict = (keys) => {
        keys.forEach((k) => store.removeItem(k));
        index = index.filter((k) => !keys.includes(k));
    };
    const limit = LIMITS[base(path)];
    if (limit) {
        const sameScreen = index.filter((k) => base(pathOf(k)) === base(path));
        evict(sameScreen.slice(0, Math.max(0, sameScreen.length - limit)));
    }
    evict(index.slice(0, Math.max(0, index.length - MAX_ENTRIES)));
    saveIndex(index);
}

// storage full: drop the oldest entries and try once more, else that screen simply works online-only
function save(key, value) {
    const store = storage();
    try {
        store.setItem(key, value);
    } catch {
        const index = readJson(INDEX_KEY, []);
        index.slice(0, 10).forEach((k) => store.removeItem(k));
        saveIndex(index.slice(10));
        store.setItem(key, value);
    }
}

// Taken when a request starts and handed back to remember() with its reply: if the user signed out or the
// currency changed in between, the reply no longer belongs in the cache.
export function cacheTicket() {
    return {generation, scope: currentScope()};
}

export function remember(path, data, {get = true, ticket = cacheTicket()} = {}) {
    const store = storage();
    if (!store || ticket.generation !== generation) return;
    try {
        let scope = currentScope();
        // the profile names the user and currency every other entry is filed under
        if (USER_PATHS.includes(base(path)) && data?.id != null && data?.currency) {
            scope = `${data.id}:${data.currency}`;
            store.setItem(SCOPE_KEY, JSON.stringify(scope));
        } else if (scope === null || ticket.scope !== scope) {
            return; // unknown user yet, or saved under a currency that has since changed
        }
        if (!get || !cacheable(path)) return;
        const key = keyFor(scope, path);
        save(key, JSON.stringify(data));
        touch(key, path);
    } catch {
        // storage full or unavailable: the app works online-only for that screen
    }
}

// the saved response for the current user and currency, or undefined when there isn't one
export function recall(path) {
    const store = storage();
    const scope = currentScope();
    if (!store || scope === null || !cacheable(path)) return undefined;
    try {
        const key = keyFor(scope, path);
        const saved = store.getItem(key);
        if (saved === null) return undefined;
        touch(key, path);
        return JSON.parse(saved);
    } catch {
        return undefined;
    }
}

export function forgetAll() {
    if (!isNative) return;
    generation += 1;
    const store = storage();
    if (!store) return;
    try {
        Object.keys(store)
            .filter((key) => key.startsWith(PREFIX) || key === SCOPE_KEY || key === INDEX_KEY)
            .forEach((key) => store.removeItem(key));
    } catch {
        // nothing to clear
    }
}
