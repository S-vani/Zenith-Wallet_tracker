import {useState} from "react";
import {Link} from "react-router-dom";
import {requestVerification} from "../services/api.js";
import PasswordInput from "./PasswordInput.jsx";
import GoogleButton from "./GoogleButton.jsx";
import {showToast} from "../utils/toast.js";
import {isNative} from "../native/platform.js";
import {LegalLinks} from "../components/LegalLayout.jsx";
import {passwordChecks} from "./passwordRules.js";

// Sign up: name, email, password (with its rules shown live) and display currency.
function SignupForm({onSubmit}) {
    const [form, setForm] = useState({
        email: "",
        password: "",
        name: "",
        currency: "CAD"
    });
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [registeredEmail, setRegisteredEmail] = useState(null);
    const [resent, setResent] = useState(false);

    const handleChange = (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!form.name.trim()) {
            setError("Please enter your name.");
            return;
        }
        setSubmitting(true);
        setError(null);

        try {
            await onSubmit(form);
            showToast("Account created successfully!");
            setRegisteredEmail(form.email.trim());
        } catch (err) {
            setError(err.message);
        } finally {
            setSubmitting(false);
        }
    };

    if (registeredEmail) {
        return (
            <main className="signup-form-side" id="main-content" tabIndex={-1}>
                <div className="signup-form-card signup-success">
                    <div className="success-icon" aria-hidden="true">✓</div>
                    <div className="signup-form-header">
                        <h1>Check your inbox</h1>
                        <p>
                            We sent a verification link to <strong>{registeredEmail}</strong>. Click it to activate your
                            account, then log in.
                            {isNative && " The link opens in Safari; come back to Zenith afterwards."}
                        </p>
                    </div>
                    <Link to="/login" className="auth-btn signup-btn large signup-submit-btn">Go to log in</Link>
                    <div className="signup-form-footer">
                        <span>Didn't get it?</span>
                        <button
                            type="button"
                            className="hero-link-btn"
                            disabled={resent}
                            onClick={async () => {
                                try {
                                    await requestVerification(registeredEmail);
                                    setResent(true);
                                } catch (err) {
                                    // e.g. the one-email-a-minute limit: say so instead of claiming it was sent
                                    showToast(err.message, {type: "error"});
                                }
                            }}
                        >
                            {resent ? "Sent again" : "Resend email"}
                        </button>
                    </div>
                </div>
            </main>
        );
    }

    return (
        <main className="signup-form-side" id="main-content" tabIndex={-1}>
            <div className="signup-form-card">
                <div className="signup-form-header">
                    <span className="preview-label">Get started</span>
                    <h1>Create your account</h1>
                    <p>Set up your dashboard and start tracking your investments.</p>
                </div>

                {error && <p className="alert-error" role="alert">{error}</p>}

                <GoogleButton label="Sign up with Google"/>

                <form className="signup-form" onSubmit={handleSubmit}>
                    <div className="signup-field">
                        <label htmlFor="name">Full name</label>
                        <input
                            id="name"
                            name="name"
                            placeholder="Jane Doe"
                            value={form.name}
                            onChange={handleChange}
                            autoComplete="name"
                            maxLength={100}
                            required
                            autoFocus
                        />
                    </div>

                    <div className="signup-field">
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
                        />
                    </div>

                    <div className="signup-field">
                        <label htmlFor="password">Password</label>
                        <PasswordInput
                            id="password"
                            name="password"
                            placeholder="At least 8 characters"
                            value={form.password}
                            onChange={handleChange}
                            autoComplete="new-password"
                            minLength={8}
                            aria-describedby="password-rules"
                            required
                        />
                        <PasswordChecklist password={form.password} email={form.email}/>
                    </div>

                    <div className="signup-field">
                        <label htmlFor="currency">Preferred currency</label>
                        <select
                            id="currency"
                            name="currency"
                            value={form.currency}
                            onChange={handleChange}
                            required
                        >
                            <option value="CAD">CAD — Canadian Dollar</option>
                            <option value="USD">USD — US Dollar</option>
                            <option value="EUR">EUR — Euro</option>
                        </select>
                    </div>

                    <button type="submit" className="auth-btn signup-btn large signup-submit-btn" disabled={submitting}>
                        {submitting ? "Creating account…" : "Create account"}
                    </button>
                    <p className="signup-legal">
                        By creating an account you agree to the <Link to="/terms">Terms of Use</Link> and{" "}
                        <Link to="/privacy">Privacy Policy</Link>. Zenith is not financial advice.
                    </p>
                </form>

                <div className="signup-form-footer">
                    <span>Already have an account?</span>
                    <Link to="/login" className="hero-link-btn">Log in</Link>
                </div>
                <LegalLinks/>
            </div>
        </main>
    );
}

// Live checklist under the password field. The live region is always in the page (a region added together with
// its text often isn't announced), but it stays empty until the user starts typing, so it doesn't nag up front.
function PasswordChecklist({password, email}) {
    return (
        <div id="password-rules" className="password-rules" aria-live="polite">
            {password && (
                <>
                    <ul className="password-rules-list">
                        {passwordChecks(password, email).map((check) => (
                            <li key={check.id} className={check.met ? "met" : undefined}>
                                <span className="password-rules-icon" aria-hidden="true">{check.met ? "✓" : "○"}</span>
                                {check.label}
                                <span className="visually-hidden">{check.met ? " (done)" : " (not yet)"}</span>
                            </li>
                        ))}
                    </ul>
                    {/* only the server has the common-password list, so the checklist doesn't tick it off */}
                    <p className="password-rules-note">Very common passwords are also refused when you sign up.</p>
                </>
            )}
        </div>
    );
}

export default SignupForm;
