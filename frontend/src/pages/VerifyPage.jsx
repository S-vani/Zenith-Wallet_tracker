import {useEffect, useRef, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {verify} from "../services/api"
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css"
import "../css/Auth.css"
import "../css/Login.css"

function VerifyPage() {
    usePageTitle("Verify email");

    const [params] = useSearchParams();
    const token = params.get("token");
    const [status, setStatus] = useState(token ? "loading" : "error");
    const [message, setMessage] = useState(
        token ? "" : "This verification link is missing its token. Try the link from your email again."
    );
    const requested = useRef(false); // StrictMode runs effects twice; a token can only be used once

    useEffect(() => {
        if (requested.current || !token) return;
        requested.current = true;

        verify(token)
            .then(() => setStatus("success"))
            .catch((err) => {
                setStatus("error");
                setMessage(err.message);
            });
    }, [token]);

    return (
        <div className="verify-page">
            <div className="login-form-card verify-card">
                {status === "loading" && (
                    <>
                        <div className="spinner"/>
                        <h1>Verifying your email…</h1>
                    </>
                )}

                {status === "success" && (
                    <>
                        <div className="success-icon" aria-hidden="true">✓</div>
                        <h1>You're verified!</h1>
                        <p>Your email has been confirmed. You can now log in to your dashboard.</p>
                        <Link to="/login" className="auth-btn signup-btn large">Log in</Link>
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
        </div>
    )
}

export default VerifyPage;
