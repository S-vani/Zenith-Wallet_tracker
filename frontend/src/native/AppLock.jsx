import {useCallback, useEffect, useRef, useState} from "react";
import {useNavigate} from "react-router-dom";
import {getToken, logout} from "../services/api.js";
import {biometricInfo, isPrompting, verifyIdentity} from "./biometric.js";
import {haptic} from "./haptics.js";

// a quick app switch (answering a text) doesn't ask again
const GRACE_MS = 30 * 1000;

// Face ID lock for the app. When it's on, the portfolio is covered whenever the app goes to the background
// (so it also stays hidden in the app switcher) and Face ID / passcode opens it again.
function AppLock({initiallyEnabled}) {
    const navigate = useNavigate();
    const [enabled, setEnabled] = useState(initiallyEnabled);
    const [locked, setLocked] = useState(initiallyEnabled && Boolean(getToken()));
    const [label, setLabel] = useState("Face ID");
    const [failed, setFailed] = useState(false);
    const prompting = useRef(false);

    useEffect(() => {
        biometricInfo().then((info) => setLabel(info.label));
    }, []);

    // no state changes before the first await, so this can be started from an effect
    const unlock = useCallback(async () => {
        if (prompting.current) return;
        prompting.current = true;
        try {
            await verifyIdentity("Unlock Zenith to see your portfolio");
            haptic("success");
            setFailed(false);
            setLocked(false);
        } catch {
            setFailed(true);
        } finally {
            prompting.current = false;
        }
    }, []);

    // ask straight away when the app opens locked
    // (on the next tick, once the lock screen is on screen behind the Face ID sheet)
    useEffect(() => {
        if (!locked) return;
        const id = setTimeout(unlock, 0);
        return () => clearTimeout(id);
        // only on mount: later locks are handled by the resume listener below
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const onSetting = (e) => setEnabled(Boolean(e.detail));
        const onBackground = () => {
            if (enabled && getToken() && !isPrompting()) setLocked(true);
        };
        const onResume = (e) => {
            if (!enabled || !getToken() || isPrompting()) return;
            if ((e.detail?.away ?? 0) < GRACE_MS) setLocked(false);
            else unlock();
        };
        window.addEventListener("app:lock-setting", onSetting);
        window.addEventListener("app:background", onBackground);
        window.addEventListener("app:resume", onResume);
        return () => {
            window.removeEventListener("app:lock-setting", onSetting);
            window.removeEventListener("app:background", onBackground);
            window.removeEventListener("app:resume", onResume);
        };
    }, [enabled, unlock]);

    if (!locked) return null;

    const signOut = () => {
        logout();
        setLocked(false);
        navigate("/login", {replace: true});
    };

    return (
        <div className="app-lock" role="dialog" aria-modal="true" aria-labelledby="app-lock-title">
            <img className="app-lock-logo" src="/zenith-logo.svg" alt="" width="84" height="84"/>
            <h1 id="app-lock-title">Zenith is locked</h1>
            <p>{failed ? `${label} didn't work. Try again or use your passcode.` : `Use ${label} to open your portfolio.`}</p>
            <button type="button" className="auth-btn signup-btn large" onClick={unlock}>Unlock with {label}</button>
            <button type="button" className="app-lock-signout" onClick={signOut}>Sign out instead</button>
        </div>
    );
}

export default AppLock;
