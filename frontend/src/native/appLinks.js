import {isNative} from "./platform.js";
import {APP_SCHEME} from "../utils/appLink.js";

// App only: zenithwallet:// links (from the "Open the Zenith app" button on the verify / reset password pages)
// open the app on a screen. bootstrap.js hears them (appUrlOpen) before React may have rendered, so the screen is
// kept here until the router picks it up (AppLinkNavigator in App.jsx), and also announced with "app:navigate".
// Home Screen quick actions and Siri use the same hand-over (showAppScreen, from screens.js).

// Every screen a link may open. Anything else (or anything with extra data) is ignored: any app or website can
// open a custom scheme URL, so it must never carry tokens or be able to reach arbitrary routes.
const ROUTES = {
    login: "/login",
};

let pending = null;

// "zenithwallet://login" -> "/login"; null for anything unknown
export function appLinkPath(url) {
    if (typeof url !== "string") return null;
    let parsed;
    try {
        parsed = new URL(url);
    } catch {
        return null;
    }
    if (parsed.protocol !== `${APP_SCHEME}:`) return null;
    // "zenithwallet://login" puts "login" in the host; also accept "zenithwallet:login" / "zenithwallet:///login"
    const target = (parsed.host || parsed.pathname.replace(/^\/+/, "")).replace(/\/+$/, "").toLowerCase();
    return Object.hasOwn(ROUTES, target) ? ROUTES[target] : null;
}

// Opens the screen a zenithwallet:// link asks for (only known ones); no-op on the website.
export function handleAppUrl(url) {
    if (!isNative) return;
    const path = appLinkPath(url);
    if (path) showAppScreen({path});
}

// {path, state}: a screen the app was asked to open from outside the web view
export function showAppScreen(screen) {
    if (!isNative) return;
    pending = screen;
    window.dispatchEvent(new CustomEvent("app:navigate", {detail: screen}));
}

// the screen ({path, state}) a link asked for that the router hasn't shown yet (read once)
export function takePendingAppLink() {
    const path = pending;
    pending = null;
    return path;
}
