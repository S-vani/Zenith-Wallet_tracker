import {useEffect, useRef, useState} from "react";
import {Link, useLocation, useNavigate, useSearchParams} from "react-router-dom";
import {requestVerification} from "../services/api.js";
import {showToast} from "../utils/toast.js";
import PasswordInput from "./PasswordInput.jsx";
import GoogleButton from "./GoogleButton.jsx";
import {LegalLinks} from "../components/LegalLayout.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import {isNative} from "../native/platform.js";
import {biometricInfo} from "../native/biometric.js";
import {
    faceIdLoginEmail, forgetFaceIdLogin, markFaceIdOffered, rememberLoginForFaceId, savedLoginAfterFaceId,
    shouldOfferFaceId, turnOnFaceId,
} from "../native/faceIdLogin.js";

// reasons the backend can send back after a failed Google sign in
const GOOGLE_ERRORS = {
    cancelled: "Google sign in was cancelled.",
    expired: "Google sign in took too long. Please try again.",
    invalid_state: "Google sign in couldn't be verified. Please try again.",
    google_error: "Google couldn't complete the sign in. Please try again.",
    no_email: "Your Google account didn't share an email address.",
    inactive: "This account has been deactivated.",
    google_not_configured: "Google sign in isn't available right now.",
};


// Email and password sign in, with the reasons a sign in can fail spelled out.
function LoginForm({onSubmit}) {
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const googleError = searchParams.get("oauth_error");

    const [form, setForm] = useState({
        "email": "",
        "password": ""
    });
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(
        googleError ? (GOOGLE_ERRORS[googleError] ?? "Google sign in failed. Please try again.") : null
    );
    const [needsVerification, setNeedsVerification] = useState(false);
    const [notice, setNotice] = useState(
        location.state?.notice ?? (location.state?.expired ? "Your session expired. Please log in again." : null)
    );

    // App only: "Log in with Face ID" once a login is saved for it (faceIdLogin.js), and after a password sign in
    // the one-time "Use Face ID?" question. The label is what the phone asks for (Face ID, Touch ID or passcode).
    const [faceIdEmail, setFaceIdEmail] = useState(null);
    const [biometryLabel, setBiometryLabel] = useState("Face ID");
    const [offer, setOffer] = useState(null); // the login to keep if they say yes
    const autoAsked = useRef(false);

    const finish = () => {
        // the app just opens the dashboard; the website confirms with a toast
        if (!isNative) showToast("Logged in"); // neutral: this is also a brand-new account's very first sign in
        navigate(location.state?.from ?? "/dashboard", {replace: true});
    };

    const signInWithFaceId = async () => {
        setSubmitting(true);
        setError(null);
        let saved;
        try {
            saved = await savedLoginAfterFaceId();
        } catch {
            setSubmitting(false); // cancelled or not recognised: the password form is right there
            return;
        }
        try {
            await onSubmit(saved);
            finish();
        } catch (err) {
            if (err.message === "Incorrect email or password.") {
                // the password was changed (maybe on the website): the saved one is useless now
                await forgetFaceIdLogin();
                setFaceIdEmail(null);
                setForm((prev) => ({...prev, email: saved.email}));
                setError(`Your password has changed. Log in with it once to use ${biometryLabel} again.`);
            } else {
                setError(err.message);
            }
            setSubmitting(false);
        }
    };

    // Opening the app (or coming back after the idle sign out) goes straight to Face ID, like a banking app; after
    // a deliberate Log out it waits for a tap instead.
    useEffect(() => {
        if (!isNative) return;
        let cancelled = false;
        (async () => {
            const [email, info] = await Promise.all([faceIdLoginEmail(), biometricInfo()]);
            if (cancelled || !email) return;
            setFaceIdEmail(email);
            setBiometryLabel(info.label);
            if (!location.state?.loggedOut && !autoAsked.current) {
                autoAsked.current = true;
                signInWithFaceId();
            }
        })();
        return () => {
            cancelled = true;
        };
        // once, when the screen opens
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleChange = (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        })
    };

    const handleSubmit = async (e) => {
        e.preventDefault()
        setSubmitting(true);
        setError(null);
        setNotice(null);
        setNeedsVerification(false);

        try {
            await onSubmit(form);
            if (isNative) {
                await rememberLoginForFaceId(form.email, form.password); // only kept while the lock is on
                if (await shouldOfferFaceId()) {
                    setBiometryLabel((await biometricInfo()).label);
                    setOffer({email: form.email, password: form.password});
                    return; // the dialog's answer finishes the sign in
                }
            }
            finish();
        } catch (err) {
            setError(err.message);
            setNeedsVerification(err.message.includes("verify"));
            setSubmitting(false);
        }
    };

    const answerOffer = async (yes) => {
        const login = offer;
        setOffer(null);
        await markFaceIdOffered();
        if (yes) {
            try {
                await turnOnFaceId(login.email, login.password);
            } catch {
                // not confirmed: it can be turned on later in Account
            }
        }
        finish();
    };

    const resendVerification = async () => {
        try {
            await requestVerification(form.email);
            setError(null);
            setNeedsVerification(false);
            setNotice(`Verification email sent to ${form.email.trim()}. Check your inbox.`);
        } catch (err) {
            setError(err.message);
        }
    };

    return (
        <main className="login-form-side" id="main-content" tabIndex={-1}>
            <div className="login-form-card">
                <div className="login-form-header">
                    <span className="preview-label">Welcome back</span>
                    <h1>Log in to your account</h1>
                    <p>Enter your email and password to access your dashboard.</p>
                </div>

                {notice && (
                    // an expired session is a warning; other notices ("Password changed…") are good news
                    <p className={location.state?.expired && !location.state?.notice ? "alert-warning" : "alert-success"}
                       role="status">{notice}</p>
                )}
                {error && (
                    <div className="alert-error" role="alert">
                        {error}
                        {needsVerification && form.email && (
                            <button type="button" className="inline-link" onClick={resendVerification}>
                                Resend verification email
                            </button>
                        )}
                    </div>
                )}

                {faceIdEmail && (
                    <button type="button" className="faceid-login-btn" onClick={signInWithFaceId}
                            disabled={submitting}>
                        <FaceIdGlyph/>
                        <span className="faceid-login-text">
                            Log in with {biometryLabel}
                            <small>{faceIdEmail}</small>
                        </span>
                    </button>
                )}

                <GoogleButton next={location.state?.from ?? "/dashboard"}/>

                <form className="login-form" onSubmit={handleSubmit}>
                    <div className="login-field">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            name="email"
                            type="email"
                            placeholder="you@example.com"
                            value={form.email}
                            onChange={handleChange}
                            autoComplete="email"
                            required
                            autoFocus={!isNative} /* the app opens on Face ID or the keyboard, not both */
                        />
                    </div>

                    <div className="login-field">
                        <label htmlFor="password">Password</label>
                        <PasswordInput
                            id="password"
                            name="password"
                            placeholder="Enter your password"
                            value={form.password}
                            onChange={handleChange}
                            autoComplete="current-password"
                            required
                        />
                        {/* below the field, so Tab goes from email straight to the password */}
                        <Link to="/forgot-password" className="forgot-link">Forgot password?</Link>
                    </div>

                    <button type="submit" className="auth-btn signup-btn large login-submit-btn" disabled={submitting}>
                        {submitting ? "Logging in…" : "Log in"}
                    </button>
                </form>

                <div className="login-form-footer">
                    <span>Don't have an account?</span>
                    <Link to="/signup" className="hero-link-btn">Sign up</Link>
                </div>
                <LegalLinks/>
            </div>

            <ConfirmDialog
                open={Boolean(offer)}
                title={`Use ${biometryLabel}?`}
                message={`Open Zenith and log in with ${biometryLabel} instead of typing your password. You can turn this off in Account.`}
                confirmLabel={`Use ${biometryLabel}`}
                cancelLabel="Not now"
                onConfirm={() => answerOffer(true)}
                onCancel={() => answerOffer(false)}
            />
        </main>
    )

}

// The Face ID mark (a face in a rounded frame), drawn like the SF Symbol
function FaceIdGlyph() {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
             aria-hidden="true">
            <path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/>
            <path d="M9 9.5v1M15 9.5v1M12 9.5v3.5h-1M9.5 15.5c1.4 1.2 3.6 1.2 5 0"/>
        </svg>
    );
}

export default LoginForm
