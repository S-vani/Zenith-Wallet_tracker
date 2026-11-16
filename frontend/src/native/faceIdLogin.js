import {isNative, loadPlugin} from "./platform.js";
import {biometricInfo, isLockEnabled, setLockEnabled, verifyIdentity} from "./biometric.js";

// "Log in with Face ID" on the sign in screen. With the Face ID lock on, the email and password from the last
// password sign in are kept in the iOS Keychain (on this phone only, never sent anywhere else), and Face ID unlocks
// them to sign in again after a log out or the 10-minute idle sign out. Turning the lock off forgets them.
const biometric = loadPlugin(() => import("@capgo/capacitor-native-biometric"));
const preferences = loadPlugin(() => import("@capacitor/preferences"));
const LOGIN_SERVER = "ca.zenithwalletracker.app.login";
const OFFERED_KEY = "faceIdLoginOffered"; // "Use Face ID next time?" is asked once per phone

// The saved email when Face ID sign in can be offered (app, lock on, a login saved), else null.
export async function faceIdLoginEmail() {
    if (!isNative || (await isLockEnabled()) !== true) return null;
    try {
        const {NativeBiometric} = await biometric();
        const {username} = await NativeBiometric.getCredentials({server: LOGIN_SERVER});
        return username || null;
    } catch {
        return null; // nothing saved
    }
}

// Face ID first, then the saved email and password. Rejects when Face ID is cancelled or fails.
export async function savedLoginAfterFaceId() {
    await verifyIdentity("Log in to Zenith");
    const {NativeBiometric} = await biometric();
    const {username, password} = await NativeBiometric.getCredentials({server: LOGIN_SERVER});
    return {email: username, password};
}

// Keeps this login for Face ID sign in. Does nothing unless the Face ID lock is on.
export async function rememberLoginForFaceId(email, password) {
    if (!isNative || (await isLockEnabled()) !== true) return;
    try {
        const {NativeBiometric} = await biometric();
        await NativeBiometric.setCredentials({username: email.trim(), password, server: LOGIN_SERVER});
    } catch {
        // without it the sign in screen just asks for the password, as before
    }
}

// Forgets the saved login (lock turned off, the password no longer works, account deleted). No-op on the website.
export async function forgetFaceIdLogin() {
    if (!isNative) return;
    try {
        const {NativeBiometric} = await biometric();
        await NativeBiometric.deleteCredentials({server: LOGIN_SERVER});
    } catch {
        // nothing was saved
    }
}

// After a password sign in: whether to ask "Use Face ID?" (app, Face ID or a passcode set up, lock off, not
// asked on this phone before).
export async function shouldOfferFaceId() {
    if (!isNative) return false;
    try {
        if ((await isLockEnabled()) !== false) return false; // already on (or unknown)
        const {available} = await biometricInfo();
        if (!available) return false;
        const {Preferences} = await preferences();
        return (await Preferences.get({key: OFFERED_KEY})).value !== "yes";
    } catch {
        return false;
    }
}

// Remembers that the question was asked, whatever the answer.
export async function markFaceIdOffered() {
    try {
        const {Preferences} = await preferences();
        await Preferences.set({key: OFFERED_KEY, value: "yes"});
    } catch {
        // asking again next time is harmless
    }
}

// "Use Face ID": confirms with Face ID once, turns the lock on and keeps this login for Face ID sign in.
export async function turnOnFaceId(email, password) {
    await verifyIdentity("Use Face ID to open Zenith");
    await setLockEnabled(true);
    await rememberLoginForFaceId(email, password);
}
