import {isNative} from "../native/platform.js";

// The App Store lists the app as "Zenith: Portfolio Tracker" (Apple's reviewers expect the in-app name to match the
// store listing), so pages shown inside the app use that name; the website keeps "Zenith Wallet Tracker".
export const BRAND_ACCENT = isNative ? "Portfolio Tracker" : "Wallet Tracker";
export const BRAND_NAME = isNative ? "Zenith: Portfolio Tracker" : "Zenith Wallet Tracker";
