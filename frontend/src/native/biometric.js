import {isNative, loadPlugin} from "./platform.js";
import {biometryLabel} from "./lockRules.js";

const biometricPlugin = loadPlugin(() => import("@capgo/capacitor-native-biometric"));
const preferences = loadPlugin(() => import("@capacitor/preferences"));
const LOCK_KEY = "biometricLock";

// {available, label} where label is what the phone will actually ask for ("Face ID", "Touch ID", or "Passcode"
// when no face / finger is enrolled)
export async function biometricInfo() {
    if (!isNative) return {available: false, label: "Face ID"};
    try {
        const {NativeBiometric} = await biometricPlugin();
        const result = await NativeBiometric.isAvailable({useFallback: true});
        return {available: result.isAvailable, label: biometryLabel(result)};
    } catch {
        return {available: false, label: "Face ID"};
    }
}

// The Face ID sheet makes iOS report the app as inactive/active, which looks exactly like leaving and coming back.
// - While the sheet is open, "leaving" events are the sheet itself, so the lock ignores them (isPromptOpen).
// - The "coming back" event can arrive just after the sheet closes, so returns are ignored for a moment longer
//   (isSettling). Leaving is never ignored then: an app left right after unlocking must still be covered.
let promptOpen = false;
let settleUntil = 0;

// Whether the Face ID sheet is up right now.
export function isPromptOpen() {
    return promptOpen;
}

// Whether the Face ID sheet is up or has only just closed.
export function isSettling() {
    return promptOpen || Date.now() < settleUntil;
}

// Resolves when the person is verified; rejects if they cancel or fail. The passcode is offered as a fallback.
export async function verifyIdentity(reason = "Unlock Zenith") {
    const {NativeBiometric} = await biometricPlugin();
    promptOpen = true;
    try {
        await NativeBiometric.verifyIdentity({
            reason,
            title: "Unlock Zenith",
            useFallback: true,
            fallbackTitle: "Use passcode",
        });
    } finally {
        promptOpen = false;
        settleUntil = Date.now() + 1500;
    }
}

// true / false, or null when the setting couldn't be read (callers then treat the lock as on: fail closed)
export async function isLockEnabled() {
    if (!isNative) return false;
    try {
        const {Preferences} = await preferences();
        return (await Preferences.get({key: LOCK_KEY})).value === "on";
    } catch {
        return null;
    }
}

// Turns the lock on or off (saved for the next launch) and tells the app.
export async function setLockEnabled(enabled) {
    const {Preferences} = await preferences();
    if (enabled) await Preferences.set({key: LOCK_KEY, value: "on"});
    else await Preferences.remove({key: LOCK_KEY});
    window.dispatchEvent(new CustomEvent("app:lock-setting", {detail: enabled}));
}

// Signing out on purpose (Log out, "Sign out instead", account deletion) turns the lock off: it belongs to that
// session, and a fresh sign in starts without it (and without the native app switcher cover). An expired session
// keeps it (api.js logout({keepLock})): the same person signs back in and expects it still on. No-op on the website.
export function resetLockOnSignOut() {
    if (!isNative) return;
    setLockEnabled(false).catch(() => null);
}
