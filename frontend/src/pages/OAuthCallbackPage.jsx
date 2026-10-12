import {useEffect, useRef} from "react";
import {useNavigate} from "react-router-dom";
import {saveToken} from "../services/api.js";
import {showToast} from "../utils/toast.js";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css"

// Google sign in lands here with the login token in the URL fragment (#token=...)
function OAuthCallbackPage() {
    usePageTitle("Signing in");

    const navigate = useNavigate();
    const handled = useRef(false);

    useEffect(() => {
        if (handled.current) return;
        handled.current = true;

        const params = new URLSearchParams(window.location.hash.slice(1));
        const token = params.get("token");

        // remove the token from the address bar and browser history straight away
        window.history.replaceState(null, "", window.location.pathname);

        if (!token) {
            navigate("/login", {replace: true});
            showToast("Google sign in didn't complete. Please try again.", {type: "error"});
            return;
        }

        saveToken(token);
        showToast(params.get("new") === "1" ? "Account created with Google. Welcome!" : "Signed in with Google");

        const next = params.get("next");
        navigate(next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard", {replace: true});
    }, [navigate]);

    return (
        <div className="not-found-page">
            <div className="spinner"/>
            <p>Signing you in…</p>
        </div>
    );
}

export default OAuthCallbackPage;
