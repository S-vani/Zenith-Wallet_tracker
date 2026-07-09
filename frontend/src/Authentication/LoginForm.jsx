import {useState} from "react";
import {useNavigate} from "react-router-dom";


function LoginForm({onSubmit}) {
    const [form, setForm] = useState({
        "username": "",
        "password": ""
    });

    const handleChange = async (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        })
    };

    const handleSubmit = async (e) => {
        e.preventDefault()

        onSubmit(form, navigate);
    };

    const navigate = useNavigate();

    return (
        <div className="login-form-side">
            <div className="login-form-card">
                <div className="login-form-header">
                    <span className="preview-label">Welcome back</span>
                    <h2>Log in to your account</h2>
                    <p>Enter your credentials to access your dashboard.</p>
                </div>

                <form className="login-form" onSubmit={handleSubmit}>
                    <div className="login-field">
                        <label htmlFor="username">Username</label>
                        <input
                            id="username"
                            name="username"
                            placeholder="Enter your username"
                            onChange={handleChange}
                        />
                    </div>

                    <div className="login-field">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            name="password"
                            placeholder="Enter your password"
                            onChange={handleChange}
                            type="password"
                            autoComplete="off"
                        />
                    </div>

                    <button type="submit" className="auth-btn signup-btn large login-submit-btn">
                        Submit
                    </button>
                </form>

                <div className="login-form-footer">
                    <span>Don't have an account?</span>
                    <button onClick={() => navigate("/signup")} type="button" className="hero-link-btn">Sign up</button>
                </div>
            </div>
        </div>
    )

}

export default LoginForm
