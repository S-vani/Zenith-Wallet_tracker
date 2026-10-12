import {Link} from "react-router-dom";
import usePageTitle from "../utils/usePageTitle.js";
import {getToken} from "../services/api.js";

import "../css/Home.css"

function NotFoundPage() {
    usePageTitle("Page not found");

    return (
        <div className="not-found-page">
            <span className="not-found-code">404</span>
            <h1>This page doesn't exist</h1>
            <p>The link may be broken, or the page may have moved.</p>
            <Link to={getToken() ? "/dashboard" : "/"} className="auth-btn signup-btn large">
                {getToken() ? "Back to dashboard" : "Back to home"}
            </Link>
        </div>
    );
}

export default NotFoundPage;
