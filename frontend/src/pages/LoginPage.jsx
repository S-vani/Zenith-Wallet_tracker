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
                        <span className="brand-name">Zenith&nbsp;<span className="brand-accent">Wallet Tracker</span></span>
                    </div>
                </div>
                <div className="login-page-information">
                    <h3>Sho</h3>
                    <h2>Is a no go, bro</h2>
                    <p>Hello there kind sir they call me the lorem ipsum of all lorem ipsums</p>
                    <img src="../../public/assets/close.png" alt=""/>
                </div>

            </div>
            <LoginForm onSubmit={loginAuthentication}/>
        </div>

    )
}

export default LoginPage
