import {isNative, loadPlugin} from "./platform.js";
import {restoreToken} from "./secureToken.js";
import {isLockEnabled} from "./biometric.js";
import {haptic} from "./haptics.js";
import {getConnectivity, setOnline} from "./connectivity.js";
import {watchNumbers} from "./fitNumbers.js";
import {applyPreferredTextSize} from "./textZoom.js";
import {openLinksInAppBrowser} from "./externalLinks.js";
import {loadAppVersion} from "./appVersion.js";
import {handleAppUrl} from "./appLinks.js";
import {renewSessionIfOld} from "../services/api.js";
import {watchScreenRequests} from "./screens.js";

const appPlugin = loadPlugin(() => import("@capacitor/app"));
const networkPlugin = loadPlugin(() => import("@capacitor/network"));
const statusBarPlugin = loadPlugin(() => import("@capacitor/status-bar"));
const splashPlugin = loadPlugin(() => import("@capacitor/splash-screen"));
const keyboardPlugin = loadPlugin(() => import("@capacitor/keyboard"));

// coming back after this long reloads the data on screen (prices will have moved)
const REFRESH_AFTER_MS = 60 * 1000;

// Runs before React renders. On the website it returns straight away and changes nothing.
export async function initNative() {
    if (!isNative) return {lockEnabled: false};

    document.documentElement.classList.add("native");
    // apps don't pinch-zoom their own UI (the website keeps zoom for accessibility)
    document.querySelector('meta[name="viewport"]')
        ?.setAttribute("content", "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover");

    // these don't depend on the login, so they start even if the Keychain below is slow
    statusBarPlugin()
        .then(({StatusBar, Style}) => StatusBar.setStyle({style: Style.Dark})) // light text on the navy theme
        .catch(() => null);
    watchAppState();
    watchNetwork();
    watchKeyboard();
    addHaptics();
    watchNumbers();
    privacyBackGoesBack();
    openLinksInAppBrowser();
    applyPreferredTextSize(); // the iPhone's Text Size setting, capped so layouts still fit
    // the version every request reports (X-Zenith-App-Version); read alongside the Keychain so the first requests
    // carry it. It never fails: without it requests just go out without the header.
    const versionRead = loadAppVersion();

    await restoreToken(); // must finish before the first render, which checks for a token
    watchScreenRequests(); // a Home Screen quick action or Siri may have opened the app on a screen
    const lockEnabled = await isLockEnabled();
    await versionRead;
    renewSessionIfOld(); // in the background: the current token works meanwhile
    return {lockEnabled};
}

// Called once the first screen has rendered, so the launch image hands over without a blank flash
export function hideSplash() {
    if (!isNative) return;
    splashPlugin().then(({SplashScreen}) => SplashScreen.hide()).catch(() => null);
}

// Turns the app's lifecycle into window events: app:background, app:pause, app:resume (with time away).
function watchAppState() {
    let backgroundedAt = null;
    appPlugin().then(({App}) => {
        // "inactive": Control Center, the app switcher, a call... or the Face ID sheet (see biometric.js)
        App.addListener("appStateChange", ({isActive}) => {
            if (!isActive) {
                backgroundedAt = Date.now();
                window.dispatchEvent(new Event("app:background"));
                return;
            }
            const away = backgroundedAt ? Date.now() - backgroundedAt : 0;
            window.dispatchEvent(new CustomEvent("app:resume", {detail: {away}}));
            if (away > REFRESH_AFTER_MS) {
                window.dispatchEvent(new Event("app:refresh"));
                window.dispatchEvent(new Event("focus")); // UserContext reloads the profile on focus
            }
        });
        // "pause" only comes when the app has really left the screen (home swipe, another app), never for the
        // Face ID sheet, so the lock can tell the two apart
        App.addListener("pause", () => window.dispatchEvent(new Event("app:pause")));
        App.addListener("resume", () => {
            applyPreferredTextSize(); // Text Size may have been changed in Settings while the app was away
            renewSessionIfOld(); // a phone left unopened for a week: keep the sign in fresh
        });
        // zenithwallet://login from the "Open the Zenith app" button after verifying an email or resetting a
        // password in Safari (appLinks.js). The launch URL covers a cold start, in case its event came before
        // this listener; opening the same screen twice is harmless.
        App.addListener("appUrlOpen", ({url}) => handleAppUrl(url));
        App.getLaunchUrl()
            .then((launch) => launch?.url && handleAppUrl(launch.url))
            .catch(() => null);
    }).catch(() => null);
}

// Keeps the online / offline state (and the banner) up to date, and reloads after being offline.
function watchNetwork() {
    networkPlugin().then(async ({Network}) => {
        // listen first, then read the current state, so a change in between isn't lost
        Network.addListener("networkStatusChange", ({connected}) => {
            // also sent for Wi-Fi <-> mobile data switches that never went offline: only a real return reloads
            const wasOffline = !getConnectivity().online;
            setOnline(connected);
            window.dispatchEvent(new CustomEvent("app:network", {detail: {connected}}));
            if (connected && wasOffline) window.dispatchEvent(new Event("app:refresh")); // catch up after being offline
        });
        const {connected} = await Network.getStatus();
        setOnline(connected);
        window.dispatchEvent(new CustomEvent("app:network", {detail: {connected}}));
    }).catch(() => null);
}

// The web view shrinks above the keyboard (resize "native" in capacitor.config.json) and the field being typed in
// is scrolled into the space that's left. The Prev/Next/Done bar stays: the decimal keypad (prices, quantities)
// has no return key, so Done is the only way to close it. While the keyboard is up <html> has "keyboard-open"
// and Native.css hides the bottom tab bar, which would otherwise sit right above the keys and eat the space.
function watchKeyboard() {
    keyboardPlugin().then(({Keyboard}) => {
        Keyboard.setAccessoryBarVisible({isVisible: true}).catch(() => null);
        const classes = document.documentElement.classList;
        Keyboard.addListener("keyboardWillShow", () => classes.add("keyboard-open"));
        Keyboard.addListener("keyboardWillHide", () => classes.remove("keyboard-open"));
        Keyboard.addListener("keyboardDidShow", () => {
            const field = document.activeElement;
            if (field?.matches?.("input, textarea, select, [contenteditable=true]")) {
                field.scrollIntoView({block: "center", behavior: "smooth"});
            }
        });
    }).catch(() => null);
}

// The policy pages' (privacy, terms, support) "Back to the app" link goes to the dashboard, which suits the
// website. In the app they are opened from another screen (Account, sign in, another policy page), so "Back"
// returns there, like a native back button. Runs in the capture phase, before React Router's own click handling;
// with no earlier page in this session the link works as usual.
function privacyBackGoesBack() {
    document.addEventListener("click", (e) => {
        const link = e.target.closest?.(".legal-page .home-auth a");
        if (!link || !(window.history.state?.idx > 0)) return; // idx: React Router's position in the history
        e.preventDefault();
        e.stopPropagation();
        window.history.back();
    }, true);
}

// A light haptic when a tab, range or toggle actually changes.
function addHaptics() {
    // a light tap when a tab, range pill or toggle actually changes, from one listener instead of editing every
    // button. Tapping the tab or option that's already selected does nothing, so it doesn't buzz either.
    document.addEventListener("click", (e) => {
        const target = e.target.closest?.(".segmented button, [role=group] button, .nav-link");
        if (target && !isAlreadySelected(target)) haptic("light");
    }, true);
    // success / error buzz for every toast ("Buy of AAPL saved", errors...)
    window.addEventListener("app:toast", (e) => haptic(e.detail?.type === "error" ? "error" : "success"));
}

// exported for the tests
export function isAlreadySelected(element) {
    return element.getAttribute("aria-current") === "page" // the tab bar's current page (NavLink)
        || element.getAttribute("aria-pressed") === "true"
        || element.getAttribute("aria-selected") === "true"
        || element.getAttribute("aria-checked") === "true" && element.getAttribute("role") === "radio"
        || element.classList.contains("active")
        || element.disabled === true;
}
