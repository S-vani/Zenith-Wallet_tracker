import {Component} from "react";

// Catches rendering crashes so users see a way out instead of a blank page. The crash's own message is never shown:
// it's developer text ("Cannot read properties of undefined…") and could include data from the page.
class ErrorBoundary extends Component {
    state = {failed: false};

    static getDerivedStateFromError() {
        return {failed: true};
    }

    componentDidCatch(error, info) {
        if (import.meta.env.DEV) console.error("Render crash:", error, info?.componentStack);
    }

    // render the page again (a crash from a passing glitch, e.g. a half-loaded response, often doesn't repeat)
    retry = () => {
        this.setState({failed: false});
    };

    // This sits outside the router, so move the URL and tell the router with a popstate (what Back would send)
    // instead of a full page load, which in the app would also re-run the start-up and the Face ID lock
    goToDashboard = () => {
        window.history.pushState(null, "", "/dashboard");
        window.dispatchEvent(new PopStateEvent("popstate"));
        this.setState({failed: false});
    };

    render() {
        if (!this.state.failed) {
            return this.props.children;
        }

        return (
            <main id="main-content" tabIndex={-1} className="not-found-page">
                <span className="not-found-code">Oops</span>
                <h1>Something went wrong</h1>
                <p role="alert">Something went wrong. Please try again.</p>
                <div className="error-boundary-actions">
                    <button type="button" className="auth-btn signup-btn large" onClick={this.retry}>
                        Try again
                    </button>
                    <button type="button" className="auth-btn login-btn large" onClick={this.goToDashboard}>
                        Go to dashboard
                    </button>
                </div>
            </main>
        );
    }
}

export default ErrorBoundary;
