import {useEffect} from "react";
import {useNavigate} from "react-router-dom";
import {takePendingAppLink} from "./appLinks.js";

// App only: shows the screen a zenithwallet:// link asked for (appLinks.js). A link that opened the app before
// React rendered is waiting in takePendingAppLink; later ones arrive as "app:navigate". Renders nothing.
// /login itself sends someone who is already signed in on to the dashboard.
function AppLinkNavigator() {
    const navigate = useNavigate();

    useEffect(() => {
        const go = () => {
            const path = takePendingAppLink();
            if (path) navigate(path, {replace: true});
        };
        go();
        window.addEventListener("app:navigate", go);
        return () => window.removeEventListener("app:navigate", go);
    }, [navigate]);

    return null;
}

export default AppLinkNavigator;
