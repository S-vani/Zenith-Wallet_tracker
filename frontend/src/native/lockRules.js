// The Face ID lock's decisions, kept pure so they can be unit tested (test/native.test.js).

// a quick app switch (answering a text) doesn't ask again
export const GRACE_MS = 30 * 1000;

// Locked on the first render? enabled is null when the setting couldn't be read before the 3 s startup limit.
// The login may not be restored from the Keychain yet either, so an unknown setting locks regardless of the token
// (fail closed); onStartup() then decides once both are known.
export function initiallyLocked({enabled, signedIn}) {
    if (enabled === null) return true;
    return enabled && signedIn;
}

// After a slow start, once the login and the setting are known: "open" (signed out, or the lock is off) or "ask".
// A setting that still can't be read counts as on.
export function onStartup({enabled, signedIn}) {
    return !signedIn || enabled === false ? "open" : "ask";
}

// When the app goes inactive ("leaving", e.g. Control Center or the app switcher) or to the background
// (backgrounded: it has really left): cover it? Also remembers whether it was unlocked at that moment.
// An open Face ID sheet makes the app inactive without leaving, so that alone is ignored. But leaving *while* the
// sheet is open (home swipe during "turn off the lock") still reaches the background, and that is always covered.
export function onLeave({enabled, signedIn, promptOpen, locked, backgrounded = false}) {
    if (!enabled || !signedIn) return {cover: false};
    if (promptOpen && !backgrounded) return {cover: false};
    return {cover: true, unlockedWhenLeft: !locked};
}

// When the app becomes active again: "ignore", "unlock" (quick return to an app that was unlocked when it was
// left) or "ask" (Face ID / passcode). Being locked when leaving, e.g. after cancelling Face ID, never unlocks.
// "settling" = the Face ID sheet is closing; a return then is the sheet's own event, not the user coming back.
export function onReturn({enabled, signedIn, settling, locked, unlockedWhenLeft, away}) {
    if (!enabled || !signedIn || settling || !locked) return "ignore";
    const quickReturn = typeof away === "number" && away < GRACE_MS;
    return quickReturn && unlockedWhenLeft ? "unlock" : "ask";
}

// What to call the lock, from NativeBiometric.isAvailable(). Face ID hardware with no face enrolled still reports
// FACE_ID as its type, but then only the passcode works, so it's called "Passcode".
export const TOUCH_ID = 1; // BiometryType.TOUCH_ID in @capgo/capacitor-native-biometric

export function biometryLabel({isAvailable, strongBiometryIsAvailable, biometryType} = {}) {
    if (isAvailable && !strongBiometryIsAvailable) return "Passcode";
    return biometryType === TOUCH_ID ? "Touch ID" : "Face ID";
}
