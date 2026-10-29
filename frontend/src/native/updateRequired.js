import {isNative} from "./platform.js";

// App only: when the server answers 426 (this app version is no longer supported), request() calls requireUpdate
// and UpdateRequired.jsx covers the whole app until the person installs the new version. It never goes away by
// itself: every request would get the same answer. On the website none of this runs (the screen isn't mounted).

export const DEFAULT_UPDATE_MESSAGE = "This version of Zenith is no longer supported. Please update the app to keep using it.";

let message = null;
const listeners = new Set();

// the readable text from a 426 body ({"detail": "...", "code": "UPDATE_REQUIRED"}), with a fallback
export function updateMessageFrom(body) {
    const detail = body?.detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (typeof detail?.message === "string" && detail.message.trim()) return detail.message.trim();
    return DEFAULT_UPDATE_MESSAGE;
}

// the App Store address as a link the web view hands to iOS: https://apps.apple.com/... becomes itms-apps://...,
// which opens the App Store app directly (an https link would open in the in-app browser, see externalLinks.js).
// null when it isn't set or isn't an App Store address, and the button is hidden.
export function appStoreLink(url) {
    if (typeof url !== "string" || !url.trim()) return null;
    let parsed;
    try {
        parsed = new URL(url.trim());
    } catch {
        return null;
    }
    if (parsed.protocol === "itms-apps:") return parsed.href;
    if (parsed.protocol !== "https:" || !/(^|\.)apple\.com$/.test(parsed.hostname)) return null;
    return `itms-apps://${parsed.host}${parsed.pathname}${parsed.search}`;
}

// Shows the "Update required" screen with the server's message (app only).
export function requireUpdate(text) {
    if (!isNative) return;
    const next = text || DEFAULT_UPDATE_MESSAGE;
    if (next === message) return;
    message = next;
    document.documentElement.classList.add("update-required");
    window.dispatchEvent(new Event("app:locked")); // closes an open "are you sure?" box, which would block this screen
    listeners.forEach((listener) => listener());
}

// null until an update is required, then the message to show
export function getUpdateRequired() {
    return message;
}

// Calls `listener` when an update becomes required; returns the unsubscribe function.
export function subscribeUpdateRequired(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}
