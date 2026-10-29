import {isNative, loadPlugin} from "./platform.js";
import {showAppScreen} from "./appLinks.js";
import {formatMoney, formatPercent} from "../utils/format.js";

const preferences = loadPlugin(() => import("@capacitor/preferences"));

// App only. Native code opens the app on a screen from outside the web view: the Home Screen quick actions (press
// and hold the icon) and Siri / Shortcuts / Spotlight (ios/App/App/ZenithShortcuts.swift). It writes the screen's
// name where @capacitor/preferences keeps "pendingScreen" (UserDefaults), then sends "zenith:screen" if the web view
// is already running; on a cold start it's read here at launch. Only these names are accepted.
const PENDING_KEY = "pendingScreen";
const SCREENS = {
    dashboard: {path: "/dashboard"},
    "add-trade": {path: "/transactions", state: {openAdd: true}},
    search: {path: "/search"},
    holdings: {path: "/holdings"},
};

// Shows the screen native code asked for, if any, and forgets the request.
export async function takeScreenRequest() {
    if (!isNative) return;
    try {
        const {Preferences} = await preferences();
        const {value} = await Preferences.get({key: PENDING_KEY});
        if (!value) return;
        await Preferences.remove({key: PENDING_KEY});
        if (Object.hasOwn(SCREENS, value)) showAppScreen(SCREENS[value]);
    } catch {
        // no request (or Preferences unavailable): the app opens where it would anyway
    }
}

// Listens for screen requests from native code and checks for one made before launch.
export function watchScreenRequests() {
    if (!isNative) return;
    window.addEventListener("zenith:screen", takeScreenRequest);
    takeScreenRequest();
}

// What Siri says for "What's my portfolio worth in Zenith": the dashboard's value and today's change, kept on the
// phone (never sent anywhere) when the dashboard loads, with the time so Siri never passes off an old number as
// current. ZenithShortcuts.swift reads it, only with the iPhone unlocked and never while the Face ID lock is on.
const SNAPSHOT_KEY = "siriPortfolio";

// The sentence Siri reads: value, today's change (and %) and when it was updated.
export function portfolioSentence({value, change, basis, currency, at = new Date()}) {
    const worth = `Your portfolio is worth ${formatMoney(value, currency)}`;
    const n = Number(change) || 0;
    const percent = Number(basis) > 0 ? ` (${formatPercent(Math.abs(n / basis) * 100).replace("+", "")})` : "";
    const today = Math.abs(n) < 0.005 ? ", unchanged today" :
        `, ${n > 0 ? "up" : "down"} ${formatMoney(Math.abs(n), currency)}${percent} today`;
    const time = at.toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
    return `${worth}${today}. Updated ${time}.`;
}

// Saves that sentence for Siri from the dashboard's day stats (app only).
export async function rememberPortfolioForSiri(stats, currency) {
    if (!isNative || !currency || !stats) return;
    try {
        const {Preferences} = await preferences();
        await Preferences.set({
            key: SNAPSHOT_KEY,
            value: portfolioSentence({value: stats.value, change: stats.curr_timeperiod, basis: stats.basis, currency}),
        });
    } catch {
        // Siri just says to open the app first
    }
}

// Forgets the sentence (signing out).
export async function forgetPortfolioForSiri() {
    if (!isNative) return;
    try {
        const {Preferences} = await preferences();
        await Preferences.remove({key: SNAPSHOT_KEY});
    } catch {
        // nothing saved
    }
}
