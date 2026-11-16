import {useEffect, useState} from "react";
import {useLocation, useNavigate} from "react-router-dom";
import {getToken} from "../services/api.js";
import {actionFor, backTarget, titleFor} from "./titleBarRules.js";

// The app's navigation bar, like UIKit's: clear at the top of a screen, frosted with a hairline once the page
// scrolls under it, and the screen's name fades in once its large title (.page-headers) has scrolled away. Screens
// opened from another one (Import & export, Tax report, the policy pages) get a back chevron. Renders nothing on
// the sign in screens. App only (App.jsx); NativeLook.css has the look.
function NativeTitleBar() {
    const {pathname} = useLocation();
    const navigate = useNavigate();
    const title = titleFor(pathname);
    const [scroll, setScroll] = useState({frosted: false, titled: false});

    useEffect(() => {
        const onScroll = () => {
            const y = window.scrollY;
            setScroll((prev) => (prev.frosted === y > 2 && prev.titled === y > 44 ? prev
                : {frosted: y > 2, titled: y > 44}));
        };
        onScroll();
        window.addEventListener("scroll", onScroll, {passive: true});
        return () => window.removeEventListener("scroll", onScroll);
    }, [pathname]);

    // the page leaves room for the bar only where there is one (NativeLook.css)
    useEffect(() => {
        document.documentElement.classList.toggle("has-titlebar", Boolean(title));
        return () => document.documentElement.classList.remove("has-titlebar");
    }, [title]);

    if (!title) return null;

    const action = actionFor(pathname);
    const back = backTarget(pathname, {
        canGoBack: (window.history.state?.idx ?? 0) > 0, // React Router's position in this session's history
        signedIn: Boolean(getToken()),
    });

    // a pushed screen (with a back chevron) shows its name in the bar from the start, like UIKit
    return (
        <header className={`native-titlebar${scroll.frosted ? " frosted" : ""}${scroll.titled || back ? " titled" : ""}`}>
            {back && (
                <button type="button" className="native-back"
                        onClick={() => (back.to === -1 ? navigate(-1) : navigate(back.to))}>
                    <svg viewBox="0 0 12 20" aria-hidden="true">
                        <path d="M10 2 2 10l8 8" fill="none" stroke="currentColor" strokeWidth="2.6"
                              strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                    {back.label}
                </button>
            )}
            {/* the page's own <h1> is the heading screen readers use, so this copy is hidden from them */}
            <span className="native-titlebar-title" aria-hidden="true">{title}</span>
            {action && (
                <button type="button" className="native-bar-action" aria-label={action.label}
                        onClick={() => window.dispatchEvent(new Event(action.event))}>
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" strokeWidth="2.4"
                              strokeLinecap="round"/>
                    </svg>
                </button>
            )}
        </header>
    );
}

export default NativeTitleBar;
