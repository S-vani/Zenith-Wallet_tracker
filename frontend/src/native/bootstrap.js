import {isNative, loadPlugin} from "./platform.js";
import {restoreToken} from "./secureToken.js";
import {isLockEnabled} from "./biometric.js";
import {haptic} from "./haptics.js";
import {setOnline} from "./connectivity.js";
import {watchNumbers} from "./fitNumbers.js";

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

    await restoreToken(); // must finish before the first render, which checks for a token
    const lockEnabled = await isLockEnabled();
    return {lockEnabled};
}

// Called once the first screen has rendered, so the launch image hands over without a blank flash
export function hideSplash() {
    if (!isNative) return;
    splashPlugin().then(({SplashScreen}) => SplashScreen.hide()).catch(() => null);
}

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
    }).catch(() => null);
}

function watchNetwork() {
    networkPlugin().then(async ({Network}) => {
        // listen first, then read the current state, so a change in between isn't lost
        Network.addListener("networkStatusChange", ({connected}) => {
            setOnline(connected);
            window.dispatchEvent(new CustomEvent("app:network", {detail: {connected}}));
            if (connected) window.dispatchEvent(new Event("app:refresh")); // catch up after being offline
        });
        const {connected} = await Network.getStatus();
        setOnline(connected);
        window.dispatchEvent(new CustomEvent("app:network", {detail: {connected}}));
    }).catch(() => null);
}

// The web view shrinks above the keyboard (resize "native" in capacitor.config.json) and the Prev/Next/Done bar is
// hidden; the field being typed in is scrolled into the space that's left.
function watchKeyboard() {
    keyboardPlugin().then(({Keyboard}) => {
        Keyboard.setAccessoryBarVisible({isVisible: false}).catch(() => null);
        Keyboard.addListener("keyboardDidShow", () => {
            const field = document.activeElement;
            if (field?.matches?.("input, textarea, select, [contenteditable=true]")) {
                field.scrollIntoView({block: "center", behavior: "smooth"});
            }
        });
    }).catch(() => null);
}

// The privacy page's "Back to the app" link goes to the dashboard, which suits the website. In the app the page is
// opened from Account, so "Back" returns there, like a native back button. Runs in the capture phase, before
// React Router's own click handling; with no earlier page in this session the link works as usual.
function privacyBackGoesBack() {
    document.addEventListener("click", (e) => {
        const link = e.target.closest?.(".legal-page .home-auth a");
        if (!link || !(window.history.state?.idx > 0)) return; // idx: React Router's position in the history
        e.preventDefault();
        e.stopPropagation();
        window.history.back();
    }, true);
}

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
