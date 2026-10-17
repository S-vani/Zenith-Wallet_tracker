import {useState} from "react";
import {Link} from "react-router-dom";
import {requestVerification} from "../services/api.js";
import PasswordInput from "./PasswordInput.jsx";
import GoogleButton from "./GoogleButton.jsx";
import {showToast} from "../utils/toast.js";

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
            <div className="signup-form-side">
                <div className="signup-form-card signup-success">
                    <div className="success-icon" aria-hidden="true">✓</div>
                    <div className="signup-form-header">
                        <h1>Check your inbox</h1>
                        <p>
                            We sent a verification link to <strong>{registeredEmail}</strong>. Click it to activate your
                            account, then log in.
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
                                await requestVerification(registeredEmail).catch(() => null);
                                setResent(true);
                            }}
                        >
                            {resent ? "Sent again" : "Resend email"}
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="signup-form-side">
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
                            required
                        />
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
                        By creating an account you agree to our <Link to="/privacy">privacy policy</Link>. Zenith is
                        not financial advice.
                    </p>
                </form>

                <div className="signup-form-footer">
                    <span>Already have an account?</span>
                    <Link to="/login" className="hero-link-btn">Log in</Link>
                </div>
            </div>
        </div>
    );
}

export default SignupForm;
