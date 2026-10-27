// The iPhone app registers the custom URL scheme "zenithwallet" (CFBundleURLTypes in ios/App/App/Info.plist), so
// a page opened in Safari from an email (verify, reset password) can send people back into the app.
// Never put an email address or a token in these URLs: any app could register the same scheme.
export const APP_SCHEME = "zenithwallet";
export const APP_LOGIN_URL = `${APP_SCHEME}://login`;
// whether the app is on the App Store yet: its listing URL is set once it's live
export const APP_RELEASED = Boolean(import.meta.env.VITE_IOS_APP_STORE_URL);

// true for Safari (or another browser) on an iPhone, iPod or iPad. iPadOS asks for desktop sites by default and
// then says "Macintosh", so a Mac user agent with a touch screen counts as an iPad too (Macs have no touch screen).
export function isAppleMobileBrowser({userAgent = "", maxTouchPoints = 0} = {}) {
    if (/iPhone|iPad|iPod/.test(userAgent)) return true;
    return /Macintosh/.test(userAgent) && maxTouchPoints > 1;
}
