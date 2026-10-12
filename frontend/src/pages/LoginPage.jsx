import {Link, Navigate} from "react-router-dom";
import LoginForm from "../Authentication/LoginForm.jsx";
import {getToken, loginAuthentication} from "../services/api";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css"
import "../css/Auth.css"
import "../css/Login.css"

function LoginPage() {
    usePageTitle("Log in");

    // already signed in, skip the form
    if (getToken()) {
        return <Navigate to="/dashboard" replace/>;
    }

    return (
        <div className="login-page-wrapper">
            <div className="login-page-left-side">
                <div className="login-page-brand">
                    <Link to="/" className="home-brand">
                        <span className="brand-mark">◆</span>
                        <span className="brand-name">Zenith&nbsp;<span
                            className="brand-accent">Wallet Tracker</span></span>
                    </Link>
                </div>
                <div className="login-page-information">
                    <span className="hero-eyebrow">Invest smarter</span>
                    <h2>Track your investments in one place</h2>
                    <p>
                        See your performance, monitor your holdings, and make informed decisions with a clean
                        dashboard built for long-term investors.
                    </p>
                    <img src="/assets/login_page_logo.png" alt="" loading="lazy" decoding="async"/>
                </div>

            </div>
            <LoginForm onSubmit={loginAuthentication}/>
        </div>

    )
}

export default LoginPage
