import {Link, Navigate} from "react-router-dom";
import LoginForm from "../Authentication/LoginForm.jsx";
import LoginVisual from "../Authentication/LoginVisual.jsx";
import {getToken, loginAuthentication} from "../services/api";
import usePageTitle from "../utils/usePageTitle.js";
import {isNative} from "../native/platform.js";

import "../css/Home.css"
import "../css/Auth.css"
import "../css/Login.css"

const BrandLink = isNative ? "div" : Link;

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
                    {/* in the app "/" only bounces back to log in, so the logo isn't a link there */}
                    <BrandLink className="home-brand" {...(isNative ? {} : {to: "/"})}>
                        <img className="brand-mark" src="/zenith-logo.svg" alt="" width="32" height="32"/>
                        <span className="brand-name">Zenith&nbsp;<span
                            className="brand-accent">{isNative ? "Portfolio Tracker" : "Wallet Tracker"}</span></span>
                    </BrandLink>
                </div>
                <div className="login-page-information">
                    <span className="hero-eyebrow">Invest smarter</span>
                    <h2>Track your investments in one place</h2>
                    <p>
                        See your performance, monitor your holdings, and make informed decisions with a clean
                        dashboard built for long-term investors.
                    </p>
                    <LoginVisual/>
                </div>

            </div>
            <LoginForm onSubmit={loginAuthentication}/>
        </div>

    )
}

export default LoginPage
