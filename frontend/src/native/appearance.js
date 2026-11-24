import {currentMotionLevel} from "../motion/motionLevel.js";

// The colour theme, picked under Account > Appearance on the website and in the app: "midnight" (the default navy),
// "black" (true black, easy on OLED screens) or "daylight" (a light theme). Saved on this device and applied before
// the first paint (index.html); <html data-theme> switches the colours (design/themes.css). A cosmetic choice, so
// plain localStorage is enough: if it is cleared the app is simply Midnight again.
const KEY = "appTheme";

export const THEMES = [
    {value: "midnight", label: "Midnight"},
    {value: "black", label: "Black"},
    {value: "daylight", label: "Daylight"},
];
const BROWSER_COLOUR = {midnight: "#040813", black: "#000000", daylight: "#f2f5fb"};

// The saved theme, or "midnight".
export function currentTheme() {
    try {
        const saved = localStorage.getItem(KEY);
        return THEMES.some(({value}) => value === saved) ? saved : "midnight";
    } catch {
        return "midnight";
    }
}

// Paints the page in `theme` (and the browser's address bar / status bar colour).
export function applyTheme(theme = currentTheme()) {
    document.documentElement.setAttribute?.("data-theme", theme);
    document.querySelector?.('meta[name="theme-color"]')?.setAttribute("content", BROWSER_COLOUR[theme]);
}

// Saves and applies a theme. Where the browser can (View Transitions) and the device isn't in a calm motion level, the
// new theme floods out from `origin` (the button that was pressed) in a circle; otherwise it just switches.
export function setTheme(theme, origin = null) {
    const change = () => {
        try {
            localStorage.setItem(KEY, theme);
        } catch {
            // still applied for now
        }
        applyTheme(theme);
    };
    const level = currentMotionLevel();
    if (!document.startViewTransition || level === "reduced" || level === "lite") {
        change();
        return;
    }
    const box = origin?.getBoundingClientRect?.();
    const x = box ? box.left + box.width / 2 : window.innerWidth / 2;
    const y = box ? box.top + box.height / 2 : window.innerHeight / 2;
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    const root = document.documentElement;
    root.classList.add("theme-reveal");
    const transition = document.startViewTransition(change);
    transition.ready
        .then(() => root.animate(
            {clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`]},
            {duration: 650, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)", pseudoElement: "::view-transition-new(root)"}))
        .catch(() => null);
    transition.finished.finally(() => root.classList.remove("theme-reveal"));
}
