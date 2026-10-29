import {useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {verify} from "../services/api"
import usePageTitle from "../utils/usePageTitle.js";
import OpenAppButton from "../components/OpenAppButton.jsx";

import "../css/Home.css"
import "../css/Auth.css"
import "../css/Login.css"

// Confirms an email address from the link in the verification email.
function VerifyPage() {
    usePageTitle("Verify email");

    const [params] = useSearchParams();
    const token = params.get("token");
    // Verifying waits for a click: email scanners and link previews open links on their own, and that alone
    // shouldn't confirm an account for whoever registered the address
    const [status, setStatus] = useState(token ? "ready" : "error");
    const [message, setMessage] = useState(
        token ? "" : "This verification link is missing its token. Try the link from your email again."
    );

    const handleVerify = () => {
        setStatus("loading");
        verify(token)
            .then(() => setStatus("success"))
            .catch((err) => {
                if (err.message.includes("already verified")) {
                    setStatus("success"); // e.g. the link was opened twice
                    return;
                }
                setStatus("error");
                setMessage(err.message);
            });
    };

    return (
        <main className="verify-page" id="main-content" tabIndex={-1}>
            <div className="login-form-card verify-card">
                {status === "ready" && (
                    <>
                        <h1>Confirm your email</h1>
                        <p>Click the button below to verify your email address and activate your Zenith account.</p>
                        <button type="button" className="auth-btn signup-btn large" onClick={handleVerify}>
                            Verify my email
                        </button>
                        <p className="verify-app-note">Didn't sign up for Zenith? You can close this page.</p>
                    </>
                )}

                {status === "loading" && (
                    <>
                        <div className="spinner" aria-hidden="true"/>
                        <h1 role="status">Verifying your email…</h1>
                    </>
                )}

                {status === "success" && (
                    <>
                        <div className="success-icon" aria-hidden="true">✓</div>
                        <h1>You're verified!</h1>
                        <p>Your email has been confirmed. You can now log in to your dashboard.</p>
                        <Link to="/login" className="auth-btn signup-btn large">Log in</Link>
                        <OpenAppButton/>
                        {/* verification links always open in the browser, even for people who signed up in the app */}
                        <p className="verify-app-note">Signed up in the Zenith iPhone app? Go back to the app and log in there.</p>
                    </>
                )}

                {status === "error" && (
                    <>
                        <div className="success-icon error" aria-hidden="true">!</div>
                        <h1>We couldn't verify your email</h1>
                        <p>{message}</p>
                        <Link to="/login" className="auth-btn signup-btn large">Back to log in</Link>
                    </>
                )}
            </div>
        </main>
    )
}

export default VerifyPage;
