import {useEffect} from "react";
import {useNavigate} from "react-router-dom";
import {getToken} from "../services/api.js";
import {registerPushIfAllowed} from "./push.js";

// App only (App.jsx): at startup, re-registers this phone for notifications when the person already allowed them,
// which also starts listening for taps, so a notification that opened the app goes to its screen. Renders nothing.
function PushNavigator() {
    const navigate = useNavigate();
    useEffect(() => {
        if (getToken()) registerPushIfAllowed(navigate);
        // once, at startup; sign ins register again themselves (LoginForm)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return null;
}

export default PushNavigator;
