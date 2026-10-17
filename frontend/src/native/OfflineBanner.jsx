import {useEffect, useState} from "react";
import {online} from "./bootstrap.js";

// Native "no connection" strip at the top, instead of every page failing with its own error
function OfflineBanner() {
    const [offline, setOffline] = useState(!online);

    useEffect(() => {
        const onNetwork = (e) => setOffline(!e.detail.connected);
        window.addEventListener("app:network", onNetwork);
        return () => window.removeEventListener("app:network", onNetwork);
    }, []);

    if (!offline) return null;
    return (
        <div className="offline-banner" role="status">
            You're offline. Showing what was last loaded.
        </div>
    );
}

export default OfflineBanner;
