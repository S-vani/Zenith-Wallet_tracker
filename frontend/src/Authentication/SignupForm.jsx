import {useState} from "react";
import {useNavigate} from "react-router-dom";

function SignupForm({onSubmit}) {
    const [form, setForm] = useState({
        email: "",
        password: "",
        name: ""
    });

    const handleChange = async (e) => {
        setForm({
            ...form,
            [e.target.name]: e.target.value
        });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        onSubmit(form);
    };

    const navigate = useNavigate();


    return (
        <div className="signup-form-side">
            <div className="signup-form-card">
                <div className="signup-form-header">
                    <span className="preview-label">Get started</span>
                    <h2>Create your account</h2>
                    <p>Set up your dashboard and start tracking your investments.</p>
                </div>

                <form className="signup-form" onSubmit={handleSubmit}>
                    <div className="signup-field">
                        <label htmlFor="name">Full Name</label>
                        <input
                            id="name"
                            name="name"
                            placeholder="Enter your full name"
                            onChange={handleChange}
                        />
                    </div>

                    <div className="signup-field">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            name="email"
                            placeholder="Enter your email"
                            onChange={handleChange}
                        />
                    </div>

                    <div className="signup-field">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            name="password"
                            placeholder="Create a password"
                            onChange={handleChange}
                            type="password"
                            autoComplete="off"
                        />
                    </div>

                    <button type="submit" className="auth-btn signup-btn large signup-submit-btn">
                        Submit
                    </button>
                </form>

                <div className="signup-form-footer">
                    <span>Already have an account?</span>
                    <button onClick={() => navigate("/login")} type="button" className="hero-link-btn">Log in</button>
                </div>
            </div>
        </div>
    );
}

export default SignupForm;
