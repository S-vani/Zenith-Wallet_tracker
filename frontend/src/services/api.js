import {saveToken as keepInKeychain} from "../native/secureToken.js";
import {cacheTicket, forgetAll, recall, remember} from "../native/offlineCache.js";
import {markFresh, markStale, requestStarted, requestTimeout} from "../native/connectivity.js";
import {resetLockOnSignOut} from "../native/biometric.js";
import {isNative} from "../native/platform.js";
import {appVersionHeaders} from "../native/appVersion.js";
import {requireUpdate, updateMessageFrom} from "../native/updateRequired.js";
import {forgetLastAccount} from "../utils/accounts.js";
import {forgetPortfolioForSiri} from "../native/screens.js";

const BASE_URL = import.meta.env.VITE_BACKEND_URL;

// Friendly messages for the error codes fastapi-users sends back
const ERROR_MESSAGES = {
    LOGIN_BAD_CREDENTIALS: "Incorrect email or password.",
    LOGIN_USER_NOT_VERIFIED: "Please verify your email before logging in.",
    REGISTER_USER_ALREADY_EXISTS: "An account with that email already exists.",
    REGISTER_INVALID_PASSWORD: "That password isn't allowed. Try a longer one.",
    VERIFY_USER_BAD_TOKEN: "This verification link is invalid or has expired.",
    VERIFY_USER_ALREADY_VERIFIED: "Your email is already verified. You can log in.",
    RESET_PASSWORD_BAD_TOKEN: "This reset link is invalid or has expired. Request a new one.",
};

// Rate limits (429) come with a readable detail from the backend ("Please wait a minute…"); this is only used if
// the body couldn't be read, e.g. when nginx's own limit answered
const TOO_MANY_REQUESTS = "Too many attempts. Please wait a few minutes and try again.";

// The iPhone app asks for a long-lived login token (30 days instead of 1 hour) so it isn't signed out every hour.
// Only the app sends this header; "Log out of all devices" can still revoke those tokens.
const APP_CLIENT_HEADERS = isNative ? {"X-Zenith-Client": "ios-app"} : {};

// localStorage key of the login token; UserContext also watches it for sign-ins/outs in other tabs
export const TOKEN_KEY = "token";

// The saved sign in token, or null.
export function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

// keepLock: an expired session keeps the app's Face ID lock on for the next sign in on this phone; signing out on
// purpose (Log out, "Sign out instead", deleting the account) turns it off
export function logout({keepLock = false} = {}) {
    localStorage.removeItem(TOKEN_KEY);
    keepInKeychain(null); // the iOS app also keeps the token in the Keychain; no-op on the website
    forgetAll(); // and the app's offline copy of the portfolio screens
    if (!keepLock) resetLockOnSignOut(); // and the app's Face ID lock; no-op on the website
    forgetLastAccount(); // and the add form's remembered account, which was this person's
    forgetPortfolioForSiri(); // and the portfolio total the app keeps for Siri; no-op on the website
}

// A 401/403 for the token a request was sent with. If someone has signed in since (a slow request from before
// the sign in answering late), that old token's refusal must not sign out the new session.
function sessionExpired(sentToken) {
    if (getToken() === sentToken) {
        logout({keepLock: true});
        window.dispatchEvent(new Event("auth:expired"));
    }
    return new Error("Your session has expired. Please log in again.");
}

// JSON headers with the sign in token.
function getAuthHeaders() {
    return {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
    };
}

const FIELD_LABELS = {
    name: "Name",
    email: "Email",
    password: "Password",
    current_password: "Current password",
    new_password: "New password",
    currency: "Currency",
    quantity: "Quantity",
    price_of_one: "Price",
    asset_type: "Asset type",
    created_at: "Date",
    account_type: "Account",
};

// Turn a FastAPI/pydantic validation error into something a person can read
function validationMessage({loc = [], msg = "", ctx = {}}) {
    const field = FIELD_LABELS[loc[loc.length - 1]] ?? "This field";

    if (field === "Email" || msg.includes("email address")) return "Please enter a valid email address.";
    if (msg.includes("at least 1 character")) return `${field} can't be empty.`;
    if (ctx.max_length) return `${field} must be ${ctx.max_length} characters or fewer.`;
    if (ctx.min_length) return `${field} must be at least ${ctx.min_length} characters.`;
    if (ctx.le !== undefined) return `${field} is too large.`;
    if (ctx.gt !== undefined) return `${field} must be greater than ${ctx.gt}.`;
    return `${field}: ${msg.replace(/^Value error, /, "")}`;
}

// A readable message from an error reply (or `fallback`), never the raw detail of a server error.
async function errorMessage(res, fallback) {
    try {
        const body = await res.json();
        const detail = body?.detail;

        if (typeof detail === "string") {
            return ERROR_MESSAGES[detail] ?? detail;
        }
        if (detail?.code) {
            // the backend says which password rule failed ("too common", "one character repeated", ...); a fixed
            // "try a longer one" would be wrong for most of them
            if (detail.code === "REGISTER_INVALID_PASSWORD" && detail.reason) return detail.reason;
            return ERROR_MESSAGES[detail.code] ?? detail.reason ?? fallback;
        }
        if (Array.isArray(detail) && detail[0]?.msg) {
            return validationMessage(detail[0]);
        }
    } catch {
        // body wasn't json, use the fallback
    }
    return res.status === 429 ? TOO_MANY_REQUESTS : fallback;
}

// 426: the server no longer supports this app version (only the app sends X-Zenith-App-Version). The app shows its
// "Update required" screen; the caller gets an error, never saved data, and the person stays signed in.
async function updateRequiredError(res) {
    let body = null;
    try {
        body = await res.json();
    } catch {
        // no readable body (or the time limit hit while reading it): the default message still says what to do
    }
    const message = updateMessageFrom(body);
    requireUpdate(message); // no-op on the website
    const error = new Error(message);
    error.status = 426;
    error.code = "UPDATE_REQUIRED";
    return error;
}

// Shared fetch wrapper: attaches the token, turns error responses into readable messages,
// and signs the user out when their session is no longer valid.
// In the iOS app a request also gives up after a while (requestTimeout; never on the website), and a portfolio
// screen that can't be loaded (offline, timeout, server unreachable) shows its saved copy under the banner instead.
async function request(path, {auth = true, fallbackError = "Something went wrong. Please try again.", signal, ...options} = {}) {
    // On the website (no time limit) the caller's own signal goes to fetch untouched. In the app a second controller
    // aborts on the time limit *or* when the caller's AbortController (e.g. switching analyst symbols) fires.
    const timeoutMs = requestTimeout(path, options.method); // 0 on the website
    const controller = timeoutMs ? new AbortController() : null;
    let timedOut = false;
    const timer = controller ? setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, timeoutMs) : null;
    const cancel = () => controller.abort();
    if (controller && signal?.aborted) controller.abort();
    else if (controller) signal?.addEventListener("abort", cancel, {once: true});
    const ticket = cacheTicket(); // app only: a reply that lands after a sign out or currency change isn't saved
    const finished = requestStarted(); // app only: pull to refresh spins until the reload is done

    // no reply: a cancelled request (AbortController) isn't a connection problem, let the caller ignore it;
    // otherwise the iOS app shows what it last loaded (recall is always undefined on the website)
    const unreachable = (err) => {
        if (err?.name === "AbortError" && !timedOut) throw err;
        const saved = isGet(options) ? recall(path) : undefined;
        if (saved !== undefined) {
            markStale(); // the banner says this is saved data
            return saved;
        }
        if (timedOut && !isGet(options)) {
            // the server may still have saved it: "try again" could save a trade twice
            throw new Error("The server didn't answer in time, so this may or may not have been saved. Check " +
                "before trying again.", {cause: err});
        }
        throw new Error(timedOut
            ? "The server is taking too long to answer. Please try again."
            : "Can't reach the server. Check your connection and try again.", {cause: err});
    };

    const sentToken = auth ? getToken() : null;
    try {
        let res;
        try {
            res = await fetch(`${BASE_URL}${path}`, {
                ...options,
                signal: controller ? controller.signal : signal,
                headers: {
                    ...(auth ? getAuthHeaders() : {"Content-Type": "application/json"}),
                    ...appVersionHeaders(), // app only
                    ...options.headers,
                },
            });
        } catch (err) {
            return unreachable(err);
        }

        // before everything else: not a sign out, not an ordinary error, and nothing to save for offline use
        if (res.status === 426) {
            throw await updateRequiredError(res);
        }

        if (auth && (res.status === 401 || res.status === 403)) {
            throw sessionExpired(sentToken);
        }

        if (!res.ok) {
            const error = new Error(await errorMessage(res, fallbackError));
            error.status = res.status; // lets callers treat e.g. 429 differently
            throw error;
        }

        let data;
        try {
            data = await res.json();
        } catch (err) {
            // the timeout (or a cancel) can also land while the body is still arriving
            if (err?.name === "AbortError") return unreachable(err);
            throw err;
        }
        markFresh(); // app only: the server answered, so a "showing saved data" banner can go
        remember(path, data, {get: isGet(options), ticket}); // app only: keep a copy for offline use
        return data;
    } finally {
        if (timer) clearTimeout(timer);
        if (controller) signal?.removeEventListener("abort", cancel);
        finished();
    }
}

// Whether a request is a GET (only those can fall back to saved data).
function isGet(options) {
    return !options.method || options.method.toUpperCase() === "GET";
}

// Date inputs give "YYYY-MM-DD", which JS reads as UTC midnight. Use the local start/end of the day instead
// null for a date the browser let through but no Date can hold (a six-digit year typed into the picker): the filter
// is then simply left out instead of failing with "Invalid time value"
function startOfDay(date) {
    const day = new Date(`${date}T00:00:00`);
    return Number.isNaN(day.getTime()) ? null : day.toISOString();
}

// The end of a local day as ISO, or null for a date no Date can hold.
function endOfDay(date) {
    const day = new Date(`${date}T23:59:59.999`);
    return Number.isNaN(day.getTime()) ? null : day.toISOString();
}

// Trades matching the filters (symbol, action, account, dates), in the user's currency.
export async function getTransactions(filters = {}) {
    const params = new URLSearchParams()

    if (filters.symbol) {
        params.append("symbol", filters.symbol.trim())
    }
    if (filters.action) {
        params.append("action", filters.action)
    }
    if (filters.account_type) {
        params.append("account_type", filters.account_type) // a type, or ACCOUNT_UNSET for trades without one
    }
    const start = filters.start_date && startOfDay(filters.start_date);
    if (start) {
        params.append("start_date", start)
    }
    const end = filters.end_date && endOfDay(filters.end_date);
    if (end) {
        params.append("end_date", end)
    }

    return request(`/transactions?${params.toString()}`, {fallbackError: "Failed to load transactions."});
}

// Saves a new trade; the reply is the saved trade.
export async function createTransaction(data) {
    return request("/transactions", {
        method: "POST",
        body: JSON.stringify(data),
        fallbackError: "Failed to create transaction.",
    });
}

// Only the fields that changed; a 409 means the edit would sell more than was owned (see ledgerErrorMessage)
export async function updateTransaction(id, changes) {
    return request(`/transactions/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify(changes),
        fallbackError: "Couldn't save your changes to this trade.",
    });
}

// Deletes a trade (409 when a later sell needs it).
export async function deleteTransaction(id) {
    return request(`/transactions/${encodeURIComponent(id)}`, {
        method: "DELETE",
        fallbackError: "Couldn't delete this trade. Please try again.",
    });
}

// CSV import, step 1: what each row of the file would become (nothing is saved). `csv` is the file's text.
export async function previewImport(csv, format = "auto", defaultAccountType = null) {
    return request("/transactions/import/preview", {
        method: "POST",
        body: JSON.stringify({csv, format, default_account_type: defaultAccountType}),
        fallbackError: "Couldn't read this file. Please try again.",
    });
}

// Step 2: save the rows the user accepted, all or none. A 409 names the symbol and line that would oversell.
// `rows` are what commitRows() makes; `importId` (one per preview) makes a retry return the first answer instead of
// importing twice. Resolves to {imported, skipped_duplicates}.
export async function commitImport(rows, importId = null) {
    return request("/transactions/import", {
        method: "POST",
        body: JSON.stringify(importId ? {rows, import_id: importId} : {rows}),
        fallbackError: "Couldn't import these trades. Nothing was saved.",
    });
}

// The export and the template are CSV, not JSON, so they skip request()'s JSON parsing (and the app's offline copy).
// Resolves to {filename, text}. Content-Disposition isn't readable cross-origin (CORS doesn't expose it), so the
// file is named here, the same way the server names it.
async function requestCsv(path, filename, fallbackError) {
    let res;
    const sentToken = getToken();
    try {
        res = await fetch(`${BASE_URL}${path}`, {headers: {...getAuthHeaders(), ...appVersionHeaders()}});
    } catch (err) {
        throw new Error("Can't reach the server. Check your connection and try again.", {cause: err});
    }
    if (res.status === 426) {
        throw await updateRequiredError(res);
    }
    if (res.status === 401 || res.status === 403) {
        throw sessionExpired(sentToken);
    }
    if (!res.ok) {
        const error = new Error(await errorMessage(res, fallbackError));
        error.status = res.status;
        throw error;
    }
    return {filename, text: await res.text()};
}

// Every trade as the Zenith CSV template, named with today's date.
export async function exportTradesCsv(today = new Date()) {
    const pad = (n) => String(n).padStart(2, "0");
    const day = `${today.getUTCFullYear()}-${pad(today.getUTCMonth() + 1)}-${pad(today.getUTCDate())}`;
    return requestCsv("/transactions/export", `zenith-trades-${day}.csv`,
        "Couldn't export your trades. Please try again.");
}

// The empty import template.
export async function getImportTemplate() {
    return requestCsv("/transactions/import/template", "zenith-import-template.csv",
        "Couldn't download the template. Please try again.");
}

// Value, return and basis for a range.
export async function getDashboardStats(time_span) {
    const times = new URLSearchParams()

    if (time_span) {
        times.append("current_timeperiod", time_span)
    }

    return request(`/dashboard?${times.toString()}`, {fallbackError: "Failed to load your portfolio stats."});
}

// What's held now.
export async function getHoldings() {
    return request("/holdings", {fallbackError: "Failed to load your holdings."});
}

// `coinId` (crypto) is the exact CoinGecko coin, for tickers that several coins share
export async function getPriceHistory(symbol, type, range, coinId) {
    const params = new URLSearchParams({symbol, type, range});
    if (coinId && type === "crypto") {
        params.append("coin_id", coinId);
    }

    return request(`/prices/history?${params.toString()}`, {fallbackError: "Failed to load chart data."});
}

// Market Analyst report for one asset. `signal` cancels the request when the user switches to another asset
export async function getAnalystReport({symbol, type, coinId, refresh = false}, {signal} = {}) {
    const params = new URLSearchParams({symbol, type});

    if (coinId) {
        params.append("coin_id", coinId);
    }
    if (refresh) {
        params.append("refresh", "true");
    }

    return request(`/analyst?${params.toString()}`, {signal, fallbackError: "Couldn't load the market analysis."});
}

// The portfolio's value and invested amount over `days` (or "all").
export async function getPortfolioHistory(range) {
    return request(`/portfolio/history?range=${encodeURIComponent(range)}`, {
        fallbackError: "Failed to load portfolio chart."
    });
}

// Today's value split by asset type, account, holding and listing currency (the dashboard's Allocation card)
export async function getPortfolioAllocation() {
    return request("/portfolio/allocation", {fallbackError: "Couldn't load your allocation."});
}

// Capital gains (Canada): the years with taxable sales, newest first
export async function getCapitalGainsYears() {
    const data = await request("/reports/capital-gains/years", {fallbackError: "Couldn't load your tax years."});
    return data?.years ?? [];
}

// One calendar year's taxable sales with proceeds, ACB and gain, always in CAD
export async function getCapitalGainsReport(year) {
    return request(`/reports/capital-gains?year=${encodeURIComponent(year)}`, {
        fallbackError: "Couldn't load your capital gains report.",
    });
}

// The same report as CSV text: {filename, text}. Not through request(), which reads every answer as JSON
export async function getCapitalGainsCsv(year) {
    return requestCsv(`/reports/capital-gains.csv?year=${encodeURIComponent(year)}`,
        `zenith-capital-gains-${year}.csv`, "Couldn't download the CSV. Please try again.");
}

// Signs in; the app asks for its 30-day token.
export async function loginAuthentication(form) {
    const formData = new URLSearchParams();

    formData.append("username", form.email.trim());
    formData.append("password", form.password);

    let res;
    try {
        res = await fetch(`${BASE_URL}/auth/jwt/login`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded", ...APP_CLIENT_HEADERS, ...appVersionHeaders()},
            body: formData
        });
    } catch {
        throw new Error("Can't reach the server. Check your connection and try again.");
    }

    if (res.status === 426) {
        throw await updateRequiredError(res);
    }

    if (!res.ok) {
        throw new Error(await errorMessage(res, "Incorrect email or password."));
    }

    const data = await res.json()

    saveToken(data.access_token)

    return data
}

// Which sign in providers (e.g. Google) the backend has set up
export async function getAuthProviders() {
    return request("/auth/providers", {auth: false});
}

// Full-page redirect target that starts "Continue with Google"
export function googleSignInUrl(next = "/dashboard") {
    return `${BASE_URL}/auth/google/start?next=${encodeURIComponent(next)}`;
}

// Saves the sign in token (and the app's Keychain copy).
export function saveToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
    keepInKeychain(token);
}

// App only: the app's sign in lasts 30 days. While it's in use, a token over a week old is swapped for a fresh one
// (POST /user/token), so someone who opens the app every day is never sent back to the login screen. Called on
// launch and when the app comes back; at most one attempt an hour, and any failure just waits for the next one.
const RENEW_AFTER_DAYS = 7;
const APP_TOKEN_DAYS = 30;
let lastRenewAttempt = 0;

// How many days old a 30-day app token is, from its expiry (null when it can't be read).
export function tokenAgeDays(token, now = Date.now()) {
    try {
        const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
        return APP_TOKEN_DAYS - (payload.exp * 1000 - now) / 86400000;
    } catch {
        return null;
    }
}

// Renews the app's sign in once it's a week old (at most one try an hour).
export async function renewSessionIfOld() {
    const token = getToken();
    if (!isNative || !token || Date.now() - lastRenewAttempt < 60 * 60 * 1000) return;
    const age = tokenAgeDays(token);
    if (age === null || age < RENEW_AFTER_DAYS) return;
    lastRenewAttempt = Date.now();
    try {
        const data = await request("/user/token", {method: "POST", headers: APP_CLIENT_HEADERS});
        if (getToken() === token) saveToken(data.access_token); // unless someone signed out or in meanwhile
    } catch {
        // offline or the server is down: the current token still works, try again later
    }
}

// Creates an account (a verification email follows).
export async function signupAuthentication(form) {
    return request("/auth/register", {
        auth: false,
        method: "POST",
        body: JSON.stringify({
            email: form.email.trim(),
            password: form.password,
            name: form.name.trim(),
            currency: form.currency,
        }),
        fallbackError: "Couldn't create your account. Please try again.",
    });
}

// Sends the verification email again.
export async function requestVerification(email) {
    return request("/auth/request-verify-token", {
        auth: false,
        method: "POST",
        body: JSON.stringify({email: email.trim()}),
        fallbackError: "Couldn't send the verification email.",
    });
}

// Always succeeds (202) whether or not the email has an account, so the form can't reveal who signed up
export async function forgotPassword(email) {
    return request("/auth/forgot-password", {
        auth: false,
        method: "POST",
        body: JSON.stringify({email: email.trim()}),
        fallbackError: "Couldn't send the reset email. Please try again.",
    });
}

// Sets a new password from a reset link.
export async function resetPassword(token, password) {
    return request("/auth/reset-password", {
        auth: false,
        method: "POST",
        body: JSON.stringify({token, password}),
        fallbackError: "Couldn't reset your password. Please try again.",
    });
}

// Confirms an email address with the token from its link.
export async function verify(token) {
    return request("/auth/verify", {
        auth: false,
        method: "POST",
        body: JSON.stringify({token}),
        fallbackError: "This verification link is invalid or has expired.",
    });
}

// Stock search results with prices.
export async function searchStock(symbol) {
    return request(`/assets/search/stock?asset=${encodeURIComponent(symbol)}`, {
        fallbackError: "Stock search failed. Please try again."
    });
}

// Crypto search results with prices.
export async function searchCrypto(symbol) {
    return request(`/assets/search/crypto?asset=${encodeURIComponent(symbol)}`, {
        fallbackError: "Crypto search failed. Please try again."
    });
}

// The signed in user.
export async function getUser() {
    return request("/user", {fallbackError: "Failed to load your account."});
}

// How many people use Zenith (shown on the home page).
export async function getUserCount() {
    return request("/users", {auth: false});
}

// Changes the name and / or display currency.
export async function putUserInfo(new_info) {
    return request("/user/information", {
        method: "PUT",
        body: JSON.stringify(new_info),
        fallbackError: "Couldn't save your changes.",
    });
}

// Changing the email needs the current password; it also signs out every device
export async function putUserEmail(new_email, currentPassword) {
    return request("/user/email", {
        method: "PUT",
        body: JSON.stringify({email: new_email.trim(), current_password: currentPassword}),
        fallbackError: "Couldn't send the verification email.",
    });
}

// Signs out every other device; this one gets a fresh token back so it stays signed in
export async function changePassword(currentPassword, newPassword) {
    const data = await request("/user/password", {
        method: "POST",
        headers: APP_CLIENT_HEADERS, // the app keeps its long-lived token
        body: JSON.stringify({current_password: currentPassword, new_password: newPassword}),
        fallbackError: "Couldn't change your password. Please try again.",
    });
    saveToken(data.access_token);
    return data;
}

// Revokes every login token, this device's included; the caller signs the user out afterwards
export async function logoutAllDevices() {
    return request("/user/logout-all", {
        method: "POST",
        fallbackError: "Couldn't sign out your other devices. Please try again.",
    });
}

// Permanently deletes the account with all its transactions (needs the current password); the caller signs the
// user out afterwards
export async function deleteAccount(currentPassword) {
    return request("/user", {
        method: "DELETE",
        body: JSON.stringify({current_password: currentPassword}),
        fallbackError: "Couldn't delete your account. Please try again.",
    });
}
