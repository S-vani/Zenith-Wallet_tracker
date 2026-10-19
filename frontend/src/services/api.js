import {saveToken as keepInKeychain} from "../native/secureToken.js";
import {cacheTicket, forgetAll, recall, remember} from "../native/offlineCache.js";
import {markFresh, markStale, requestStarted, requestTimeout} from "../native/connectivity.js";
import {resetLockOnSignOut} from "../native/biometric.js";
import {isNative} from "../native/platform.js";

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

export function getToken() {
    return localStorage.getItem("token");
}

export function logout() {
    localStorage.removeItem("token");
    keepInKeychain(null); // the iOS app also keeps the token in the Keychain; no-op on the website
    forgetAll(); // and the app's offline copy of the portfolio screens
    resetLockOnSignOut(); // and the app's Face ID lock, which belongs to this sign in; no-op on the website
}

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

async function errorMessage(res, fallback) {
    try {
        const body = await res.json();
        const detail = body?.detail;

        if (typeof detail === "string") {
            return ERROR_MESSAGES[detail] ?? detail;
        }
        if (detail?.code) {
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

// Shared fetch wrapper: attaches the token, turns error responses into readable messages,
// and signs the user out when their session is no longer valid.
// In the iOS app a request also gives up after a while (requestTimeout; never on the website), and a portfolio
// screen that can't be loaded (offline, timeout, server unreachable) shows its saved copy under the banner instead.
async function request(path, {auth = true, fallbackError = "Something went wrong. Please try again.", signal, ...options} = {}) {
    // On the website (no time limit) the caller's own signal goes to fetch untouched. In the app a second controller
    // aborts on the time limit *or* when the caller's AbortController (e.g. switching analyst symbols) fires.
    const timeoutMs = requestTimeout(path); // 0 on the website
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
        throw new Error(timedOut
            ? "The server is taking too long to answer. Please try again."
            : "Can't reach the server. Check your connection and try again.", {cause: err});
    };

    try {
        let res;
        try {
            res = await fetch(`${BASE_URL}${path}`, {
                ...options,
                signal: controller ? controller.signal : signal,
                headers: auth ? {...getAuthHeaders(), ...options.headers} : {"Content-Type": "application/json", ...options.headers},
            });
        } catch (err) {
            return unreachable(err);
        }

        if (auth && (res.status === 401 || res.status === 403)) {
            logout();
            window.dispatchEvent(new Event("auth:expired"));
            throw new Error("Your session has expired. Please log in again.");
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

function isGet(options) {
    return !options.method || options.method.toUpperCase() === "GET";
}

// Date inputs give "YYYY-MM-DD", which JS reads as UTC midnight. Use the local start/end of the day instead
function startOfDay(date) {
    return new Date(`${date}T00:00:00`).toISOString();
}

function endOfDay(date) {
    return new Date(`${date}T23:59:59.999`).toISOString();
}

export async function getTransactions(filters = {}) {
    const params = new URLSearchParams()

    if (filters.symbol) {
        params.append("symbol", filters.symbol.trim())
    }
    if (filters.action) {
        params.append("action", filters.action)
    }
    if (filters.start_date) {
        params.append("start_date", startOfDay(filters.start_date))
    }
    if (filters.end_date) {
        params.append("end_date", endOfDay(filters.end_date))
    }

    return request(`/transactions?${params.toString()}`, {fallbackError: "Failed to load transactions."});
}

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

export async function deleteTransaction(id) {
    return request(`/transactions/${encodeURIComponent(id)}`, {
        method: "DELETE",
        fallbackError: "Couldn't delete this trade. Please try again.",
    });
}

export async function getDashboardStats(time_span) {
    const times = new URLSearchParams()

    if (time_span) {
        times.append("current_timeperiod", time_span)
    }

    return request(`/dashboard?${times.toString()}`, {fallbackError: "Failed to load your portfolio stats."});
}

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

export async function getPortfolioHistory(range) {
    return request(`/portfolio/history?range=${encodeURIComponent(range)}`, {
        fallbackError: "Failed to load portfolio chart."
    });
}

export async function loginAuthentication(form) {
    const formData = new URLSearchParams();

    formData.append("username", form.email.trim());
    formData.append("password", form.password);

    let res;
    try {
        res = await fetch(`${BASE_URL}/auth/jwt/login`, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded", ...APP_CLIENT_HEADERS},
            body: formData
        });
    } catch {
        throw new Error("Can't reach the server. Check your connection and try again.");
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

export function saveToken(token) {
    localStorage.setItem("token", token);
    keepInKeychain(token);
}

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

export async function resetPassword(token, password) {
    return request("/auth/reset-password", {
        auth: false,
        method: "POST",
        body: JSON.stringify({token, password}),
        fallbackError: "Couldn't reset your password. Please try again.",
    });
}

export async function verify(token) {
    return request("/auth/verify", {
        auth: false,
        method: "POST",
        body: JSON.stringify({token}),
        fallbackError: "This verification link is invalid or has expired.",
    });
}

export async function searchStock(symbol) {
    return request(`/assets/search/stock?asset=${encodeURIComponent(symbol)}`, {
        fallbackError: "Stock search failed. Please try again."
    });
}

export async function searchCrypto(symbol) {
    return request(`/assets/search/crypto?asset=${encodeURIComponent(symbol)}`, {
        fallbackError: "Crypto search failed. Please try again."
    });
}

export async function getUser() {
    return request("/user", {fallbackError: "Failed to load your account."});
}

export async function getUserCount() {
    return request("/users", {auth: false});
}

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
