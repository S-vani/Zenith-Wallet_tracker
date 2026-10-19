import {isNative, loadPlugin} from "./platform.js";

const textZoomPlugin = loadPlugin(() => import("@capacitor/text-zoom"));

// iOS's Text Size setting (Dynamic Type) scales the app's text like a native app's. Beyond 130% the cards and
// charts stop fitting a phone screen, so the accessibility sizes are capped there; smaller-than-default settings are
// followed down to 85%.
export const MIN_TEXT_ZOOM = 0.85;
export const MAX_TEXT_ZOOM = 1.3;

// TextZoom.getPreferred() value (1 = the iOS default size) -> the zoom to apply
export function textZoomFor(preferred) {
    const value = Number(preferred);
    if (!Number.isFinite(value) || value <= 0) return 1;
    return Math.min(MAX_TEXT_ZOOM, Math.max(MIN_TEXT_ZOOM, value));
}

// Called at startup and whenever the app comes back (the setting may have changed in between). On iOS the plugin
// applies it as -webkit-text-size-adjust on <body>. No-op on the website, where the browser's own zoom applies.
export async function applyPreferredTextSize() {
    if (!isNative) return;
    try {
        const {TextZoom} = await textZoomPlugin();
        const {value} = await TextZoom.getPreferred();
        await TextZoom.set({value: textZoomFor(value)});
    } catch {
        // keep the current size
    }
}
