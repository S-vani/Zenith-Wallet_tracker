import {useState} from "react";
import {Link} from "react-router-dom";
import {forgotPassword} from "../services/api.js";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css"
import "../css/Auth.css"
import "../css/Login.css"

// Step 1 of resetting a password: email a one-hour reset link. The answer is the same whether or not the
// email has an account, so this page can't be used to find out who uses Zenith.
function ForgotPasswordPage() {
    usePageTitle("Forgot password");

    const [email, setEmail] = useState("");
    const [sent, setSent] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setError(null);
        try {
            await forgotPassword(email);
            setSent(true);
        } catch (err) {
            setError(err.message);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <main className="verify-page" id="main-content" tabIndex={-1}>
            <div className="login-form-card verify-card">
                {sent ? (
                    <>
                        <div className="success-icon" aria-hidden="true">✓</div>
                        <h1>Check your inbox</h1>
                        <p>
                            If <strong>{email.trim()}</strong> has a Zenith account, we've sent it a link to choose a
                            new password. The link works for one hour.
                        </p>
                        <Link to="/login" className="auth-btn signup-btn large">Back to log in</Link>
                    </>
                ) : (
                    <>
                        <h1>Forgot your password?</h1>
                        <p>Enter your account's email and we'll send you a link to choose a new one.</p>
                        {error && <p className="alert-error" role="alert">{error}</p>}
                        <form className="reset-form" onSubmit={handleSubmit}>
                            <div className="login-field">
                                <label htmlFor="reset-email">Email</label>
                                <input id="reset-email" type="email" placeholder="you@example.com" value={email}
                                       onChange={(e) => setEmail(e.target.value)} autoComplete="email" required
                                       autoFocus/>
                            </div>
                            <button type="submit" className="auth-btn signup-btn large" disabled={submitting}>
                                {submitting ? "Sending…" : "Send reset link"}
                            </button>
                        </form>
                        <Link to="/login" className="auth-legal-link">Back to log in</Link>
                    </>
                )}
            </div>
        </main>
    );
}

export default ForgotPasswordPage;
