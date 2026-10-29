import {Link} from "react-router-dom";
import usePageTitle from "../utils/usePageTitle.js";
import {getToken} from "../services/api.js";

import "../css/Home.css"

// Any unknown address.
function NotFoundPage() {
    usePageTitle("Page not found");

    return (
        <main className="not-found-page" id="main-content" tabIndex={-1}>
            <span className="not-found-code">404</span>
            <h1>This page doesn't exist</h1>
            <p>The link may be broken, or the page may have moved.</p>
            <Link to={getToken() ? "/dashboard" : "/"} className="auth-btn signup-btn large">
                {getToken() ? "Back to dashboard" : "Back to home"}
            </Link>
        </main>
    );
}

export default NotFoundPage;
