import {useLayoutEffect} from "react";
import {useLocation} from "react-router-dom";

// how long .page-enter stays on (the animation in NativeLook.css is shorter)
const ENTER_MS = 400;

// App only: each new screen fades up into place instead of appearing at once (NativeLook.css, .page-enter). The
// animation only fills backwards, so no transform is left on the page afterwards (it would move fixed sheets).
// Renders nothing.
function PageTransition() {
    const {pathname} = useLocation();

    useLayoutEffect(() => {
        const main = document.getElementById("main-content");
        if (!main) return undefined;
        main.classList.remove("page-enter");
        void main.offsetWidth; // restart the animation when going from one screen straight to another
        main.classList.add("page-enter");
        const done = setTimeout(() => main.classList.remove("page-enter"), ENTER_MS);
        return () => clearTimeout(done);
    }, [pathname]);

    return null;
}

export default PageTransition;
