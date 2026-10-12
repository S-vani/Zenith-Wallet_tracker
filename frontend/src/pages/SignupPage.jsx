import {Link, Navigate} from "react-router-dom";
import SignupForm from "../Authentication/SignupForm.jsx";
import {getToken, signupAuthentication} from "../services/api";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css";
import "../css/Auth.css";
import "../css/Signup.css";

function SignupPage() {
    usePageTitle("Sign up");

    if (getToken()) {
        return <Navigate to="/dashboard" replace/>;
    }

    return (
        <div className="signup-page-wrapper">
            <SignupForm onSubmit={signupAuthentication}/>

            <div className="signup-page-right-side">
                <div className="signup-page-brand">
                    <Link to="/" className="home-brand">
                        <span className="brand-mark">◆</span>
                        <span className="brand-name">Zenith&nbsp;<span
                            className="brand-accent">Wallet Tracker</span></span>
                    </Link>
                </div>

                <div className="signup-page-information">
                    <h2>Everything you need to invest with confidence</h2>
                    <ul className="signup-benefits">
                        <li>
                            <span className="feature-icon">◆</span>
                            <div>
                                <h3>Real-time portfolio tracking</h3>
                                <p>See every holding update live, across stocks and crypto.</p>
                            </div>
                        </li>
                        <li>
                            <span className="feature-icon">◆</span>
                            <div>
                                <h3>Performance insights</h3>
                                <p>Understand what's driving your gains and losses over time.</p>
                            </div>
                        </li>
                        <li>
                            <span className="feature-icon">◆</span>
                            <div>
                                <h3>Stocks and crypto, one dashboard</h3>
                                <p>Log every buy and sell and see your whole portfolio in a single view.</p>
                            </div>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    );
}

export default SignupPage;
