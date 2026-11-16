// The app's navigation bar (NativeTitleBar.jsx): which screens have one, their names and where Back goes. Pure, so
// the tests can check it (test/native.test.js).

const TITLES = {
    "/dashboard": "Portfolio",
    "/search": "Search",
    "/transactions": "Transactions",
    "/holdings": "Holdings",
    "/user": "Account",
    "/import": "Import & Export",
    "/reports": "Tax Report",
    "/privacy": "Privacy",
    "/terms": "Terms of Use",
    "/support": "Support",
};

// opened from the Transactions screen's links
const UNDER_TRANSACTIONS = ["/import", "/reports"];
// opened from Account, the sign in screens or each other
const POLICY_PAGES = ["/privacy", "/terms", "/support"];

const clean = (pathname) => pathname.replace(/\/+$/, "") || "/";

// The screen's name in the bar, or null for screens without one (sign in, sign up, verify...).
export function titleFor(pathname) {
    return TITLES[clean(pathname)] ?? null;
}

// The bar's button on the right, as {label, event} (the window event the screen listens for), or null.
// Transactions gets iOS's "+" for adding a trade, in place of the website's full-width button.
export function actionFor(pathname) {
    return clean(pathname) === "/transactions" ? {label: "Add transaction", event: "app:add-trade"} : null;
}

// {to, label} for the back chevron (to = -1 means the previous screen), or null on the tab screens.
// A policy page opened straight from a link (no earlier screen) goes to Account, or to sign in when signed out.
export function backTarget(pathname, {canGoBack, signedIn}) {
    const path = clean(pathname);
    if (UNDER_TRANSACTIONS.includes(path)) return {to: "/transactions", label: "Transactions"};
    if (POLICY_PAGES.includes(path)) {
        if (canGoBack) return {to: -1, label: "Back"};
        return signedIn ? {to: "/user", label: "Account"} : {to: "/login", label: "Log in"};
    }
    return null;
}
