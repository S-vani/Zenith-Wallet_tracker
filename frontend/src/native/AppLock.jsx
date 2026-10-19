import {useCallback, useEffect, useLayoutEffect, useRef, useState} from "react";
import {useNavigate} from "react-router-dom";
import {getToken, logout} from "../services/api.js";
import {biometricInfo, isLockEnabled, isPromptOpen, isSettling, verifyIdentity} from "./biometric.js";
import {restoreToken} from "./secureToken.js";
import {haptic} from "./haptics.js";
import {initiallyLocked, onLeave, onReturn, onStartup} from "./lockRules.js";

// how long a slow start may keep waiting for the Keychain and the setting before showing the normal lock screen
const SLOW_START_WAIT_MS = 10000;

const within = (promise, ms, fallback) =>
    Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(fallback), ms))]);

// Face ID lock for the app. When it's on, the portfolio is covered whenever the app goes to the background
// (so it also stays hidden in the app switcher; the native cover in SceneDelegate.swift paints first) and
// Face ID / passcode opens it again.
// The only ways to unlock: a successful Face ID / passcode check, or coming back within GRACE_MS to an app that
// was *already unlocked* when it was left. Being locked when leaving (e.g. after cancelling Face ID) never counts.
// initiallyEnabled is null when startup took over 3 s: the login may not even be restored from the Keychain yet,
// so the app starts covered whatever the token says, waits for both, then opens or asks (lockRules.onStartup).
function AppLock({initiallyEnabled}) {
    const navigate = useNavigate();
    const slowStart = initiallyEnabled === null;
    const [enabled, setEnabled] = useState(initiallyEnabled !== false);
    const [locked, setLocked] = useState(() => initiallyLocked({enabled: initiallyEnabled, signedIn: Boolean(getToken())}));
    const [pending, setPending] = useState(slowStart); // slow start: still finding out, no buttons yet
    const [label, setLabel] = useState("Face ID");
    const [failed, setFailed] = useState(false);
    const prompting = useRef(false);
    const lockedRef = useRef(locked); // the listeners below need the current value, not the one they closed over
    const unlockedWhenLeft = useRef(false);
    const coveredThisTrip = useRef(false); // already covered since the app was last active

    const lock = useCallback((value) => {
        lockedRef.current = value;
        setLocked(value);
    }, []);

    // While covered, nothing behind the lock may stay usable: the focused field is blurred (which also closes the
    // keyboard) and html.app-locked hides the rest of the page from taps, focus and VoiceOver (Native.css).
    useLayoutEffect(() => {
        if (!locked) return;
        document.activeElement?.blur?.();
        document.documentElement.classList.add("app-locked");
        return () => document.documentElement.classList.remove("app-locked");
    }, [locked]);

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

    // On open: ask straight away when the app starts locked (once the lock screen is behind the Face ID sheet).
    // After a slow start, first wait for the login and the setting.
    useEffect(() => {
        let cancelled = false;
        if (!slowStart) {
            if (lockedRef.current) unlock();
            return;
        }
        (async () => {
            await within(restoreToken(), SLOW_START_WAIT_MS, null);
            const setting = await within(isLockEnabled(), SLOW_START_WAIT_MS, null);
            if (cancelled) return;
            const signedIn = Boolean(getToken());
            // the 3 s limit may have rendered "signed out" (the login page) before the Keychain answered
            if (signedIn && ["/", "/login"].includes(window.location.pathname)) navigate("/dashboard", {replace: true});
            setPending(false);
            if (setting === false) setEnabled(false);
            if (onStartup({enabled: setting, signedIn}) === "open") lock(false);
            else unlock();
        })();
        return () => {
            cancelled = true;
        };
        // only on mount: later locks are handled by the listeners below
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const onSetting = (e) => setEnabled(Boolean(e.detail));
        const state = () => ({
            enabled, signedIn: Boolean(getToken()), promptOpen: isPromptOpen(), settling: isSettling(),
            locked: lockedRef.current,
        });
        const leave = (backgrounded) => {
            const result = onLeave({...state(), backgrounded});
            if (!result.cover) return;
            // leaving usually sends two events (inactive, then background): the first one that covers decides
            // whether the app was unlocked when it was left
            if (!coveredThisTrip.current) unlockedWhenLeft.current = result.unlockedWhenLeft;
            coveredThisTrip.current = true;
            lock(true);
        };
        const onBackground = () => leave(false);
        const onPause = () => leave(true);
        const onResume = (e) => {
            const action = onReturn({...state(), unlockedWhenLeft: unlockedWhenLeft.current, away: e.detail?.away});
            coveredThisTrip.current = false;
            if (action === "unlock") lock(false);
            else if (action === "ask") unlock();
        };
        window.addEventListener("app:lock-setting", onSetting);
        window.addEventListener("app:background", onBackground);
        window.addEventListener("app:pause", onPause);
        window.addEventListener("app:resume", onResume);
        return () => {
            window.removeEventListener("app:lock-setting", onSetting);
            window.removeEventListener("app:background", onBackground);
            window.removeEventListener("app:pause", onPause);
            window.removeEventListener("app:resume", onResume);
        };
    }, [enabled, unlock, lock]);

    if (!locked) return null;

    const signOut = () => {
        logout(); // also turns the lock off (api.js)
        lock(false);
        navigate("/login", {replace: true});
    };

    // without an enrolled face or finger the phone only asks for the passcode, so don't promise Face ID
    const passcodeOnly = label === "Passcode";
    const message = failed
        ? (passcodeOnly ? "That didn't work. Try your passcode again." : `${label} didn't work. Try again or use your passcode.`)
        : (passcodeOnly ? "Use your passcode to open your portfolio." : `Use ${label} to open your portfolio.`);

    return (
        <div className="app-lock" role="dialog" aria-modal="true" aria-labelledby="app-lock-title">
            <img className="app-lock-logo" src="/zenith-logo.svg" alt="" width="84" height="84"/>
            <h1 id="app-lock-title">{pending ? "Opening Zenith…" : "Zenith is locked"}</h1>
            {!pending && (
                <>
                    <p>{message}</p>
                    <button type="button" className="auth-btn signup-btn large" onClick={unlock}>
                        {passcodeOnly ? "Unlock with passcode" : `Unlock with ${label}`}
                    </button>
                    <button type="button" className="app-lock-signout" onClick={signOut}>Sign out instead</button>
                </>
            )}
        </div>
    );
}

export default AppLock;
