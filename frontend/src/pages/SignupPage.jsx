import SignupForm from "../Authentication/SignupForm.jsx";
import { signupAuthentication } from "../services/api";

import "../css/Signup.css";

function SignupPage() {

    return (
        <div className="signup-page-wrapper">
            <SignupForm onSubmit={signupAuthentication} />

            <div className="signup-page-right-side">
                <div className="signup-page-brand">
                    <div className="home-brand">
                        <span className="brand-mark">◆</span>
                        <span className="brand-name">Zenith&nbsp;<span
                            className="brand-accent">Wallet Tracker</span></span>
                    </div>
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
                                <h3>One dashboard, all accounts</h3>
                                <p>Connect multiple brokerages and wallets in a single view.</p>
                            </div>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    );
}

export default SignupPage;
