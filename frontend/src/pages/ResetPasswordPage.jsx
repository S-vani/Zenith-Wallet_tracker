import {useEffect, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {resetPassword} from "../services/api.js";
import usePageTitle from "../utils/usePageTitle.js";
import OpenAppButton from "../components/OpenAppButton.jsx";
import {readSavedToken, removeTokenFromAddressBar, saveToken} from "../Authentication/resetToken.js";
import PasswordInput from "../Authentication/PasswordInput.jsx";

import "../css/Home.css"
import "../css/Auth.css"
import "../css/Login.css"

// Step 2: opened from the emailed link (/reset-password?token=...). Works for accounts made with Google too,
// which is how they get a password for the iPhone app.
function ResetPasswordPage() {
    usePageTitle("Choose a new password");

    const [params] = useSearchParams();
    // read once, then taken out of the address bar (see resetToken.js)
    const [token] = useState(() => params.get("token") || readSavedToken());
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [done, setDone] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(
        token ? null : "This reset link is missing its token. Use the link from your email again."
    );

    useEffect(() => {
        if (!token) return;
        saveToken(token);
        removeTokenFromAddressBar();
    }, [token]);

    const mismatch = confirm !== "" && confirm !== password;

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (mismatch) return;
        setSubmitting(true);
        setError(null);
        try {
            await resetPassword(token, password);
            saveToken(null); // used up
            removeTokenFromAddressBar();
            setDone(true);
        } catch (err) {
            setError(err.message);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <main className="verify-page" id="main-content" tabIndex={-1}>
            <div className="login-form-card verify-card">
                {done ? (
                    <>
                        <div className="success-icon" aria-hidden="true">✓</div>
                        <h1>Password changed</h1>
                        <p>You can now log in with your new password.</p>
                        <Link to="/login" className="auth-btn signup-btn large">Log in</Link>
                        <OpenAppButton/>
                        <p className="verify-app-note">Using the Zenith iPhone app? Go back to the app and log in there.</p>
                    </>
                ) : (
                    <>
                        <h1>Choose a new password</h1>
                        <p>Use at least 8 characters.</p>
                        {error && <p className="alert-error" role="alert">{error}</p>}
                        {token && (
                            <form className="reset-form" onSubmit={handleSubmit}>
                                <div className="login-field">
                                    <label htmlFor="new-password">New password</label>
                                    <PasswordInput id="new-password" value={password} minLength={8} required
                                                   onChange={(e) => setPassword(e.target.value)}
                                                   autoComplete="new-password" autoFocus/>
                                </div>
                                <div className="login-field">
                                    <label htmlFor="confirm-password">Confirm new password</label>
                                    <PasswordInput id="confirm-password" value={confirm} required
                                                   onChange={(e) => setConfirm(e.target.value)}
                                                   autoComplete="new-password"/>
                                    {mismatch && <span className="reset-mismatch" role="alert">Passwords don't match.</span>}
                                </div>
                                <button type="submit" className="auth-btn signup-btn large"
                                        disabled={submitting || mismatch || password.length < 8}>
                                    {submitting ? "Saving…" : "Save new password"}
                                </button>
                            </form>
                        )}
                        <Link to={token ? "/login" : "/forgot-password"} className="auth-legal-link">
                            {token ? "Back to log in" : "Request a new link"}
                        </Link>
                    </>
                )}
            </div>
        </main>
    );
}

export default ResetPasswordPage;
