// The Face ID lock's decisions, kept pure so they can be unit tested (test/native.test.js).

// a quick app switch (answering a text) doesn't ask again
export const GRACE_MS = 30 * 1000;

// When the app is about to go inactive: cover it? Also remembers whether it was unlocked at that moment.
// The Face ID sheet itself makes the app inactive; that isn't leaving the app, so it's ignored.
export function onLeave({enabled, signedIn, prompting, locked}) {
    if (!enabled || !signedIn || prompting) return {cover: false};
    return {cover: true, unlockedWhenLeft: !locked};
}

// When the app becomes active again: "ignore", "unlock" (quick return to an app that was unlocked when it was
// left) or "ask" (Face ID / passcode). Being locked when leaving, e.g. after cancelling Face ID, never unlocks.
export function onReturn({enabled, signedIn, prompting, locked, unlockedWhenLeft, away}) {
    if (!enabled || !signedIn || prompting || !locked) return "ignore";
    const quickReturn = typeof away === "number" && away < GRACE_MS;
    return quickReturn && unlockedWhenLeft ? "unlock" : "ask";
}
