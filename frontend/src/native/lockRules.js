// The Face ID lock's decisions, kept pure so they can be unit tested (test/native.test.js).

// a quick app switch (answering a text) doesn't ask again
export const GRACE_MS = 30 * 1000;

// When the app is about to go inactive: cover it? Also remembers whether it was unlocked at that moment.
// Only an open Face ID sheet is ignored (it makes the app "inactive" without leaving it).
export function onLeave({enabled, signedIn, promptOpen, locked}) {
    if (!enabled || !signedIn || promptOpen) return {cover: false};
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
