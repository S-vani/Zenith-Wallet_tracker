// The mood: how today is going, as a hue and strength for the zenith light (the glow at the top of every screen).
// Up gives a teal-green tint over the navy, down a muted rose-violet one, flat leaves the area's own blue. The
// Dashboard publishes it from today's change; the last value is kept (and applied before the first paint by the
// inline script in index.html) so every other screen and a cold start show it too, fading to neutral after
// MOOD_MAX_AGE_MS. Privacy mode forces neutral, because a coloured glow would show up/down in public.
const KEY = "mood";
export const MOOD_MAX_AGE_MS = 18 * 60 * 60 * 1000;
export const UP_HUE = 168;
export const DOWN_HUE = 335;
const BASE_ALPHA = 0.3;

// {hue, alpha} for a day's change in percent; hue is null when flat or unknown (the area tint is used).
export function moodFromChange(changePct) {
    const pct = Number(changePct);
    if (!Number.isFinite(pct) || Math.abs(pct) < 0.15) return {hue: null, alpha: BASE_ALPHA};
    const strength = Math.min(Math.abs(pct), 3) / 3; // saturates at a 3% day
    return {hue: pct > 0 ? UP_HUE : DOWN_HUE, alpha: Number((BASE_ALPHA + strength * 0.14).toFixed(3))};
}

// A stored mood, or the neutral one when it is missing, too old, or privacy mode is on.
export function effectiveMood(stored, {now = Date.now(), hidden = false} = {}) {
    if (hidden || !stored || !Number.isFinite(stored.at) || now - stored.at > MOOD_MAX_AGE_MS) {
        return {hue: null, alpha: BASE_ALPHA};
    }
    return {hue: stored.hue ?? null, alpha: stored.alpha ?? BASE_ALPHA};
}

// The area of the app a path belongs to (areas.css), for the area tint.
export function areaFor(pathname) {
    const path = pathname.replace(/\/+$/, "");
    if (path === "/search") return "search";
    if (path === "/transactions" || path === "/import" || path === "/reports") return "transactions";
    if (path === "/holdings") return "holdings";
    if (path === "/xray") return "xray";
    if (path === "/alerts") return "alerts";
    if (path === "/user") return "account";
    return "dashboard";
}

function readStored() {
    try {
        return JSON.parse(localStorage.getItem(KEY) ?? "null");
    } catch {
        return null;
    }
}

function hiddenNow() {
    try {
        return localStorage.getItem("hideAmounts") === "yes";
    } catch {
        return false;
    }
}

function paint({hue, alpha}) {
    const style = document.documentElement.style;
    if (hue === null) style.removeProperty("--light-hue"); // back to the area's hue
    else style.setProperty("--light-hue", String(hue));
    style.setProperty("--light-alpha", String(alpha));
}

// Applies the stored mood to the page (startup, and when privacy mode changes).
export function applyStoredMood() {
    paint(effectiveMood(readStored(), {hidden: hiddenNow()}));
}

// Publishes today's change: the light follows, and the value is kept for other screens and the next start.
export function publishMood(changePct) {
    const mood = moodFromChange(changePct);
    try {
        localStorage.setItem(KEY, JSON.stringify({...mood, at: Date.now()}));
    } catch {
        // still applied for now
    }
    paint(effectiveMood({...mood, at: Date.now()}, {hidden: hiddenNow()}));
}

// Sets the area tint (<html data-area>).
export function setArea(area) {
    document.documentElement.setAttribute("data-area", area);
}

// privacy mode changed (utils/privacy.js): neutral while hidden, the real mood again when shown
export function watchPrivacyForMood() {
    window.addEventListener("amounts-hidden-change", applyStoredMood);
}
