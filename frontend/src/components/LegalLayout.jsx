import {useEffect} from "react";
import {Link, useLocation} from "react-router-dom";
import {getToken} from "../services/api.js";
import {BRAND_ACCENT, BRAND_NAME} from "../utils/brand.js";

import "../css/Home.css";
import "../css/Legal.css";

// Shared shell of the public policy pages (privacy, terms, support): the landing page's top bar, an "On this page"
// list on wide screens and a footer that links the three pages to each other. The app's "Back" link handling in
// native/bootstrap.js (privacyBackGoesBack) relies on the `.legal-page .home-auth a` structure kept here.
function LegalLayout({sections = [], children}) {
    const {hash} = useLocation();
    const loggedIn = Boolean(getToken());

    // links like /privacy#disclaimer should land on that section
    useEffect(() => {
        if (!hash) return;
        document.getElementById(hash.slice(1))?.scrollIntoView();
    }, [hash]);

    return (
        <div className="home-page legal-page">
            <header className="home-topbar">
                <Link to="/" className="home-brand">
                    <img className="brand-mark" src="/zenith-logo.svg" alt="" width="32" height="32"/>
                    <span className="brand-name">Zenith&nbsp;<span className="brand-accent">{BRAND_ACCENT}</span></span>
                </Link>
                <nav className="home-auth" aria-label="Account">
                    <Link to={loggedIn ? "/dashboard" : "/"} className="auth-btn login-btn">
                        {loggedIn ? "Back to the app" : "Back to home"}
                    </Link>
                </nav>
            </header>

            <main className="legal-layout" id="main-content" tabIndex={-1}>
                <aside className="legal-toc" aria-label="On this page">
                    <span className="legal-toc-title">On this page</span>
                    {sections.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
                </aside>

                <article className="legal-content">
                    {children}
                </article>
            </main>

            <footer className="home-footer">
                <span className="footer-brand">
                    <img className="footer-mark" src="/zenith-logo.svg" alt="" width="16" height="16"/>
                    © 2026 {BRAND_NAME}
                </span>
                <LegalLinks/>
            </footer>
        </div>
    );
}

// Privacy · Terms · Support, used under the policy pages and the sign in / sign up forms
export function LegalLinks({className = ""}) {
    return (
        <nav className={`legal-links ${className}`.trim()} aria-label="Policies and help">
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
            <Link to="/support">Support</Link>
        </nav>
    );
}

export default LegalLayout;
