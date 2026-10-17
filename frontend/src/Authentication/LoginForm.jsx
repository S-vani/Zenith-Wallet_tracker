import {useState} from "react";
import {Link, useLocation, useNavigate, useSearchParams} from "react-router-dom";
import {requestVerification} from "../services/api.js";
import {showToast} from "../utils/toast.js";
import PasswordInput from "./PasswordInput.jsx";
import GoogleButton from "./GoogleButton.jsx";

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
            showToast("Logged in successfully. Welcome back!");
            navigate(location.state?.from ?? "/dashboard", {replace: true});
        } catch (err) {
            setError(err.message);
            setNeedsVerification(err.message.includes("verify"));
            setSubmitting(false);
        }
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
        <div className="login-form-side">
            <div className="login-form-card">
                <div className="login-form-header">
                    <span className="preview-label">Welcome back</span>
                    <h1>Log in to your account</h1>
                    <p>Enter your email and password to access your dashboard.</p>
                </div>

                {notice && <p className="alert-success" role="status">{notice}</p>}
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
                            autoFocus
                        />
                    </div>

                    <div className="login-field">
                        <div className="login-label-row">
                            <label htmlFor="password">Password</label>
                            <Link to="/forgot-password" className="forgot-link">Forgot password?</Link>
                        </div>
                        <PasswordInput
                            id="password"
                            name="password"
                            placeholder="Enter your password"
                            value={form.password}
                            onChange={handleChange}
                            autoComplete="current-password"
                            required
                        />
                    </div>

                    <button type="submit" className="auth-btn signup-btn large login-submit-btn" disabled={submitting}>
                        {submitting ? "Logging in…" : "Log in"}
                    </button>
                </form>

                <div className="login-form-footer">
                    <span>Don't have an account?</span>
                    <Link to="/signup" className="hero-link-btn">Sign up</Link>
                </div>
                <Link to="/privacy" className="auth-legal-link">Privacy policy &amp; disclaimer</Link>
            </div>
        </div>
    )

}

export default LoginForm
