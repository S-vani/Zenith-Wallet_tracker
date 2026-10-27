import {useEffect} from "react";
import {useNavigate} from "react-router-dom";
import {takePendingAppLink} from "./appLinks.js";

// App only: shows the screen a zenithwallet:// link, a Home Screen quick action or Siri asked for (appLinks.js). A link that opened the app before
// React rendered is waiting in takePendingAppLink; later ones arrive as "app:navigate". Renders nothing.
// /login itself sends someone who is already signed in on to the dashboard.
function AppLinkNavigator() {
    const navigate = useNavigate();

    useEffect(() => {
        const go = () => {
            const screen = takePendingAppLink();
            if (screen) navigate(screen.path, {replace: true, state: screen.state});
        };
        go();
        window.addEventListener("app:navigate", go);
        return () => window.removeEventListener("app:navigate", go);
    }, [navigate]);

    return null;
}

export default AppLinkNavigator;
