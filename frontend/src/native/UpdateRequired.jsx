import {useEffect, useRef, useSyncExternalStore} from "react";
import {appStoreLink, getUpdateRequired, subscribeUpdateRequired} from "./updateRequired.js";

// set in frontend/.env.ios (or the build environment): the app's App Store page, https://apps.apple.com/app/id...
const STORE_URL = appStoreLink(import.meta.env.VITE_IOS_APP_STORE_URL);

// App only: full-screen "Update required" after the server answered 426 to this app version. It can't be closed
// (there is no way back: the server refuses every request from this version), and it sits over everything,
// the Face ID lock included, since it shows nothing private. Native.css hides the rest of the page from taps and
// VoiceOver while <html> has the "update-required" class.
function UpdateRequired() {
    const message = useSyncExternalStore(subscribeUpdateRequired, getUpdateRequired);
    const headingRef = useRef(null);

    // move VoiceOver / keyboard focus onto the screen, away from whatever was focused behind it
    useEffect(() => {
        if (!message) return;
        document.activeElement?.blur?.();
        headingRef.current?.focus();
    }, [message]);

    if (!message) return null;
    return (
        <div className="update-screen" role="alertdialog" aria-modal="true" aria-labelledby="update-title"
             aria-describedby="update-message">
            <img className="app-lock-logo" src="/zenith-logo.svg" alt="" width="84" height="84"/>
            <h1 id="update-title" ref={headingRef} tabIndex={-1}>Update required</h1>
            <p id="update-message">{message}</p>
            {STORE_URL && (
                <a href={STORE_URL} className="auth-btn signup-btn large">Open the App Store</a>
            )}
        </div>
    );
}

export default UpdateRequired;
