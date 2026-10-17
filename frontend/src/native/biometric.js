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
// The lock screen ignores those events while a prompt is up (and briefly after), otherwise cancelling Face ID
// would count as a "quick return" and unlock the app.
let promptOpenUntil = 0;

export function isPrompting() {
    return Date.now() < promptOpenUntil;
}

// Resolves when the person is verified; rejects if they cancel or fail. The passcode is offered as a fallback.
export async function verifyIdentity(reason = "Unlock Zenith") {
    const {NativeBiometric} = await biometricPlugin();
    promptOpenUntil = Infinity;
    try {
        await NativeBiometric.verifyIdentity({
            reason,
            title: "Unlock Zenith",
            useFallback: true,
            fallbackTitle: "Use passcode",
        });
    } finally {
        promptOpenUntil = Date.now() + 1500;
    }
}

export async function isLockEnabled() {
    if (!isNative) return false;
    try {
        const {Preferences} = await preferences();
        return (await Preferences.get({key: LOCK_KEY})).value === "on";
    } catch {
        return false;
    }
}

export async function setLockEnabled(enabled) {
    const {Preferences} = await preferences();
    if (enabled) await Preferences.set({key: LOCK_KEY, value: "on"});
    else await Preferences.remove({key: LOCK_KEY});
    window.dispatchEvent(new CustomEvent("app:lock-setting", {detail: enabled}));
}
