import LoginForm from "../Authentication/LoginForm.jsx";
import {loginAuthentication} from "../services/api";

import "../css/Login.css"

function LoginPage() {



    return (
        <div className="login-page-wrapper">
            <div className="login-page-left-side">
                <div className="login-page-brand">
                    <div className="home-brand">
                        <span className="brand-mark">◆</span>
                        <span className="brand-name">Zenith&nbsp;<span
                            className="brand-accent">Wallet Tracker</span></span>
                    </div>
                </div>
                <div className="login-page-information">
                    <h3>Invest smarter</h3>
                    <h2>Track your investments in one place</h2>
                    <p>
                        See your performance, monitor your holdings, and make informed decisions with a clean
                        dashboard built for long-term investors.
                    </p>
                    <img src="../../public/assets/login_page_logo.png" alt=""/>
                </div>

            </div>
            <LoginForm onSubmit={loginAuthentication}/>
        </div>

    )
}

export default LoginPage
