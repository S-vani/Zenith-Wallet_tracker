import {useCallback, useEffect, useRef, useState} from "react";
import {useNavigate} from "react-router-dom";
import {getToken, logout} from "../services/api.js";
import {biometricInfo, isPrompting, verifyIdentity} from "./biometric.js";
import {haptic} from "./haptics.js";
import {onLeave, onReturn} from "./lockRules.js";

// Face ID lock for the app. When it's on, the portfolio is covered whenever the app goes to the background
// (so it also stays hidden in the app switcher) and Face ID / passcode opens it again.
// The only ways to unlock: a successful Face ID / passcode check, or coming back within GRACE_MS to an app that
// was *already unlocked* when it was left. Being locked when leaving (e.g. after cancelling Face ID) never counts.
function AppLock({initiallyEnabled}) {
    const navigate = useNavigate();
    const [enabled, setEnabled] = useState(initiallyEnabled);
    const [locked, setLocked] = useState(initiallyEnabled && Boolean(getToken()));
    const [label, setLabel] = useState("Face ID");
    const [failed, setFailed] = useState(false);
    const prompting = useRef(false);
    const lockedRef = useRef(locked); // the listeners below need the current value, not the one they closed over
    const unlockedWhenLeft = useRef(false);

    const lock = useCallback((value) => {
        lockedRef.current = value;
        setLocked(value);
    }, []);

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
            lock(false);
        } catch {
            setFailed(true);
        } finally {
            prompting.current = false;
        }
    }, [lock]);

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
        const state = () => ({
            enabled, signedIn: Boolean(getToken()), prompting: isPrompting(), locked: lockedRef.current,
        });
        const onBackground = () => {
            const result = onLeave(state());
            if (!result.cover) return;
            unlockedWhenLeft.current = result.unlockedWhenLeft;
            lock(true);
        };
        const onResume = (e) => {
            const action = onReturn({...state(), unlockedWhenLeft: unlockedWhenLeft.current, away: e.detail?.away});
            if (action === "unlock") lock(false);
            else if (action === "ask") unlock();
        };
        window.addEventListener("app:lock-setting", onSetting);
        window.addEventListener("app:background", onBackground);
        window.addEventListener("app:resume", onResume);
        return () => {
            window.removeEventListener("app:lock-setting", onSetting);
            window.removeEventListener("app:background", onBackground);
            window.removeEventListener("app:resume", onResume);
        };
    }, [enabled, unlock, lock]);

    if (!locked) return null;

    const signOut = () => {
        logout();
        lock(false);
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
