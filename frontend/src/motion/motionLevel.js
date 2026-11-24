// The one motion level (<html data-motion>): how much movement and how many heavy effects this device gets.
//   full     desktop website: everything
//   app      the iPhone app: drag-driven features at full quality, no WebGL scene, no stacked blur
//   lite     phone browser: no heavy effects, simple reveals
//   reduced  no movement at all (the OS setting, or the kill switch)
// The level is chosen once per device class and can only go DOWN afterwards (the person's settings, the frame
// watchdog, the server's kill switch). The inline script in index.html sets the same starting level before the first
// paint; keep the two in step. The decision is pure so it can be tested.
const ORDER = ["full", "app", "lite", "reduced"]; // calmest last

// Starting level from what we know about the device.
export function decideMotionLevel({
                                      reducedMotion = false, lowPower = false, native = false, narrow = false,
                                      coarse = false, cores = 8, memory = 8,
                                  } = {}) {
    if (reducedMotion) return "reduced";
    if (native) return lowPower ? "lite" : "app";
    if (narrow || coarse) return "lite"; // a phone or tablet in the browser
    if (lowPower || cores <= 2 || memory <= 2) return "lite";
    return "full";
}

// The calmer of two levels (a level never goes back up).
export function calmer(a, b) {
    return ORDER.indexOf(a) >= ORDER.indexOf(b) ? a : b;
}

// The level the server's kill switch asks for: "off" = reduced, "lite" = lite, anything else leaves things alone.
export function levelFromServer(fx) {
    return fx === "off" ? "reduced" : fx === "lite" ? "lite" : "full";
}

// Whether the median frame gap (ms) is too long: the watchdog lowers the level when the device can't keep up.
export function slowFrames(gaps, limitMs = 30) {
    if (gaps.length < 20) return false;
    const sorted = [...gaps].sort((x, y) => x - y);
    return sorted[Math.floor(sorted.length / 2)] > limitMs;
}

let current = null;

export function currentMotionLevel() {
    return current ?? document.documentElement.getAttribute("data-motion") ?? "full";
}

function apply(level) {
    current = level;
    document.documentElement.setAttribute("data-motion", level);
    window.dispatchEvent(new CustomEvent("fx:level", {detail: level}));
}

// Lowers the level to `level` if that is calmer than now. Returns the level in effect.
export function lowerMotionLevel(level) {
    const next = calmer(currentMotionLevel(), level);
    if (next !== current) apply(next);
    return next;
}

// Starts the level for this device and keeps following the OS reduced-motion setting. `native` = the iPhone app.
export function initMotionLevel({native = false} = {}) {
    const media = (q) => window.matchMedia?.(q).matches ?? false;
    apply(decideMotionLevel({
        reducedMotion: media("(prefers-reduced-motion: reduce)"),
        native,
        narrow: media("(max-width: 768px)"),
        coarse: media("(hover: none) and (pointer: coarse)"),
        cores: navigator.hardwareConcurrency ?? 8,
        memory: navigator.deviceMemory ?? 8,
    }));
    window.matchMedia?.("(prefers-reduced-motion: reduce)").addEventListener?.("change", (e) => {
        if (e.matches) lowerMotionLevel("reduced");
    });
    return current;
}

// For a few seconds after startup, measures frame times; a device that can't keep up gets the lite level.
export function startFrameWatchdog() {
    if (["lite", "reduced"].includes(currentMotionLevel())) return;
    const gaps = [];
    let last = 0;
    const stop = performance.now() + 3500;
    const tick = (now) => {
        if (!document.hidden) {
            if (last) gaps.push(now - last);
            last = now;
        }
        if (now < stop) requestAnimationFrame(tick);
        else if (slowFrames(gaps)) lowerMotionLevel("lite");
    };
    requestAnimationFrame(tick);
}
