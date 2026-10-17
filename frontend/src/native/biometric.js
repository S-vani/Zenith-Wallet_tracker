import {isNative, loadPlugin} from "./platform.js";

const biometricPlugin = loadPlugin(() => import("@capgo/capacitor-native-biometric"));
const preferences = loadPlugin(() => import("@capacitor/preferences"));
const LOCK_KEY = "biometricLock";

// {available, label} where label is what the phone calls it ("Face ID", "Touch ID")
export async function biometricInfo() {
    if (!isNative) return {available: false, label: "Face ID"};
    try {
        const {NativeBiometric, BiometryType} = await biometricPlugin();
        const result = await NativeBiometric.isAvailable({useFallback: true});
        const label = result.biometryType === BiometryType.TOUCH_ID ? "Touch ID" : "Face ID";
        return {available: result.isAvailable, label};
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

export function isPromptOpen() {
    return promptOpen;
}

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

export async function setLockEnabled(enabled) {
    const {Preferences} = await preferences();
    if (enabled) await Preferences.set({key: LOCK_KEY, value: "on"});
    else await Preferences.remove({key: LOCK_KEY});
    window.dispatchEvent(new CustomEvent("app:lock-setting", {detail: enabled}));
}
