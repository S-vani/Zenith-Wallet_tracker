import {Component} from "react";

// Catches rendering crashes so users see a way out instead of a blank page
class ErrorBoundary extends Component {
    state = {error: null};

    static getDerivedStateFromError(error) {
        return {error};
    }

    render() {
        if (!this.state.error) {
            return this.props.children;
        }

        return (
            <div className="not-found-page">
                <span className="not-found-code">Oops</span>
                <h1>Something went wrong</h1>
                <p>{this.state.error.message || "An unexpected error occurred."}</p>
                <div className="error-boundary-actions">
                    <button className="auth-btn signup-btn large" onClick={() => window.location.reload()}>
                        Reload page
                    </button>
                    <a className="auth-btn login-btn large" href="/dashboard">Go to dashboard</a>
                </div>
            </div>
        );
    }
}

export default ErrorBoundary;
