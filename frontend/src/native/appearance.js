import {isNative} from "./platform.js";

// The app's colour theme, picked under Account > Appearance: "midnight" (the navy the website uses) or "black" (true
// black, easy on OLED screens at night). Saved on this phone; <html data-theme> switches the colours (NativeLook.css).
// A cosmetic choice, so plain localStorage is enough: if iOS clears it the app is simply navy again.
const KEY = "appTheme";

export const THEMES = [
    {value: "midnight", label: "Midnight"},
    {value: "black", label: "Black"},
];

// The saved theme, or "midnight".
export function currentTheme() {
    try {
        return THEMES.some(({value}) => value === localStorage.getItem(KEY)) ? localStorage.getItem(KEY) : "midnight";
    } catch {
        return "midnight";
    }
}

// Paints the page in `theme` (app only; the website has one look).
export function applyTheme(theme = currentTheme()) {
    if (!isNative) return;
    document.documentElement.setAttribute?.("data-theme", theme);
}

// Saves and applies a theme.
export function setTheme(theme) {
    try {
        localStorage.setItem(KEY, theme);
    } catch {
        // still applied for now
    }
    applyTheme(theme);
}
