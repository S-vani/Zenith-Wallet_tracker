import {isNative, loadPlugin} from "./platform.js";
import {registerPushDevice} from "../services/api.js";

// Push notifications in the app (@capacitor/push-notifications; the server sends them through APNs,
// backend/services/push.py). iOS asks the person once; the phone's token is sent to the server for the signed-in
// account and kept in localStorage so a log out can unregister it (api.js logout). Tapping a notification opens
// its screen (only the app's own screens, never anything else from the payload). No-ops on the website.
const pushPlugin = loadPlugin(() => import("@capacitor/push-notifications"));
export const PUSH_TOKEN_KEY = "pushToken";

// screens a notification may open
const SCREENS = ["/dashboard", "/search", "/alerts", "/xray", "/holdings", "/transactions"];

// Whether a notification's link is one of the app's screens (path + optional query), and so safe to open.
export function safeLink(link) {
    if (typeof link !== "string" || !link.startsWith("/")) return null;
    const path = link.split("?")[0].replace(/\/+$/, "");
    return SCREENS.includes(path) ? link : null;
}

let listening = false;

// Listens for the token and for taps, once. `navigate` is React Router's.
async function listen(navigate) {
    if (listening) return;
    listening = true;
    const {PushNotifications} = await pushPlugin();
    await PushNotifications.addListener("registration", ({value}) => {
        try {
            localStorage.setItem(PUSH_TOKEN_KEY, value);
        } catch {
            // the server still gets it
        }
        registerPushDevice(value).catch(() => null);
    });
    await PushNotifications.addListener("pushNotificationActionPerformed", ({notification}) => {
        const link = safeLink(notification?.data?.link);
        if (link) navigate(link);
    });
}

// "granted", "denied" or "prompt" ("unsupported" on the website or when the plugin can't answer).
export async function pushPermission() {
    if (!isNative) return "unsupported";
    try {
        const {PushNotifications} = await pushPlugin();
        return (await PushNotifications.checkPermissions()).receive;
    } catch {
        return "unsupported";
    }
}

// Asks iOS (the first time) and registers this phone. Resolves to the permission after asking.
export async function enablePush(navigate) {
    if (!isNative) return "unsupported";
    try {
        const {PushNotifications} = await pushPlugin();
        await listen(navigate);
        let {receive} = await PushNotifications.checkPermissions();
        if (receive === "prompt" || receive === "prompt-with-rationale") {
            ({receive} = await PushNotifications.requestPermissions());
        }
        if (receive === "granted") await PushNotifications.register();
        return receive;
    } catch {
        return "unsupported";
    }
}

// After a sign in: register again (for this account) if notifications were already allowed; never asks.
export async function registerPushIfAllowed(navigate) {
    if ((await pushPermission()) === "granted") await enablePush(navigate);
}
