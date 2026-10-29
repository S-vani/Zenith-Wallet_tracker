import {isNative, loadPlugin} from "./platform.js";

const appPlugin = loadPlugin(() => import("@capacitor/app"));

// App only: the app's version (CFBundleShortVersionString, e.g. "1.2.0"), sent with every request as
// X-Zenith-App-Version so the server can answer 426 "Update required" to versions it no longer supports.
// Read once at startup (initNative); if that fails or hasn't finished, requests simply go without the header.
let version = null;

// the version as a header value, or null if it looks wrong (keeps odd strings out of a request header)
export function cleanVersion(value) {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return /^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$/.test(trimmed) ? trimmed : null;
}

// Reads the app's version once at startup, for the X-Zenith-App-Version header.
export function loadAppVersion() {
    if (!isNative) return Promise.resolve(null);
    return appPlugin()
        .then(({App}) => App.getInfo())
        .then((info) => (version = cleanVersion(info?.version)))
        .catch(() => null);
}

// extra headers for a request to our API: {} on the website and until the version is known
export function appVersionHeaders() {
    return isNative && version ? {"X-Zenith-App-Version": version} : {};
}
