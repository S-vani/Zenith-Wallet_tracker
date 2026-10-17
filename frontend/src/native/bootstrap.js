import {isNative, loadPlugin} from "./platform.js";
import {restoreToken} from "./secureToken.js";
import {isLockEnabled} from "./biometric.js";
import {haptic} from "./haptics.js";

const appPlugin = loadPlugin(() => import("@capacitor/app"));
const networkPlugin = loadPlugin(() => import("@capacitor/network"));
const statusBarPlugin = loadPlugin(() => import("@capacitor/status-bar"));
const splashPlugin = loadPlugin(() => import("@capacitor/splash-screen"));

// coming back after this long reloads the data on screen (prices will have moved)
const REFRESH_AFTER_MS = 60 * 1000;

export let online = true;

// Runs before React renders. On the website it returns straight away and changes nothing.
export async function initNative() {
    if (!isNative) return {lockEnabled: false};

    document.documentElement.classList.add("native");
    // apps don't pinch-zoom their own UI (the website keeps zoom for accessibility)
    document.querySelector('meta[name="viewport"]')
        ?.setAttribute("content", "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover");
    await restoreToken(); // must finish before the first render, which checks for a token
    const lockEnabled = await isLockEnabled();

    statusBarPlugin()
        .then(({StatusBar, Style}) => StatusBar.setStyle({style: Style.Dark})) // light text on the navy theme
        .catch(() => null);

    watchAppState();
    watchNetwork();
    addHaptics();
    return {lockEnabled};
}

// Called once the first screen has rendered, so the launch image hands over without a blank flash
export function hideSplash() {
    if (!isNative) return;
    splashPlugin().then(({SplashScreen}) => SplashScreen.hide()).catch(() => null);
}

function watchAppState() {
    let backgroundedAt = null;
    appPlugin().then(({App}) => App.addListener("appStateChange", ({isActive}) => {
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
    })).catch(() => null);
}

function watchNetwork() {
    networkPlugin().then(async ({Network}) => {
        const announce = (connected) => {
            online = connected;
            window.dispatchEvent(new CustomEvent("app:network", {detail: {connected}}));
        };
        announce((await Network.getStatus()).connected);
        Network.addListener("networkStatusChange", ({connected}) => {
            announce(connected);
            if (connected) window.dispatchEvent(new Event("app:refresh")); // catch up after being offline
        });
    }).catch(() => null);
}

function addHaptics() {
    // a light tap on toggles, range pills and tab bar buttons, from one listener instead of editing every button
    document.addEventListener("click", (e) => {
        if (e.target.closest?.(".segmented button, [role=group] button, .nav-link")) haptic("light");
    }, true);
    // success / error buzz for every toast ("Buy of AAPL saved", errors...)
    window.addEventListener("app:toast", (e) => haptic(e.detail?.type === "error" ? "error" : "success"));
}
