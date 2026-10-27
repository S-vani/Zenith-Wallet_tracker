import {APP_LOGIN_URL, APP_RELEASED, isAppleMobileBrowser} from "../utils/appLink.js";
import {isNative} from "../native/platform.js";

import "../css/OpenApp.css";

// "Open the Zenith app" next to "Log in" after verifying an email or resetting a password. Those links always open
// in the browser, even for people who use the iPhone app, so on an iPhone / iPad this takes them straight back to
// the app's log in screen (zenithwallet://login, handled in native/appLinks.js). Hidden everywhere else, and
// inside the app itself. The URL never carries the email or a token.
// Only once the app is out (VITE_IOS_APP_STORE_URL set in the website's .env too): before that nobody has it, and
// tapping the button would only show Safari's "address is invalid" alert.
function OpenAppButton() {
    if (isNative || !APP_RELEASED || typeof navigator === "undefined") return null;
    if (!isAppleMobileBrowser({userAgent: navigator.userAgent, maxTouchPoints: navigator.maxTouchPoints})) return null;

    return <a href={APP_LOGIN_URL} className="auth-btn login-btn large open-app-btn">Open the Zenith app</a>;
}

export default OpenAppButton;
