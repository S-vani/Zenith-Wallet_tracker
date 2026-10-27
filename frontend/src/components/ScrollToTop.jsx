import {useLayoutEffect} from "react";
import {useLocation, useNavigationType} from "react-router-dom";

// A new page starts at the top: following a link (the footer's Privacy · Terms · Support, the phone tab bar) used
// to open it scrolled as far down as the page left behind. Back / forward (POP) keep the browser's own restored
// position, and links to a #section are left to scroll to it. Renders nothing.
function ScrollToTop() {
    const {pathname, hash} = useLocation();
    const navigationType = useNavigationType();

    useLayoutEffect(() => {
        if (navigationType === "POP" || hash) return;
        window.scrollTo(0, 0);
    }, [pathname, hash, navigationType]);

    return null;
}

export default ScrollToTop;
