import {useSyncExternalStore} from "react";
import {getConnectivity, subscribeConnectivity} from "./connectivity.js";

// Native "no connection" strip at the top, instead of every page failing with its own error. Also shown when the
// phone is online but the server couldn't be reached, so a screen shows saved data (connectivity.js).
// useSyncExternalStore reads the state again after subscribing, so the cold-start network check can't be missed
// even when it was announced before this mounted.
function OfflineBanner() {
    const status = useSyncExternalStore(subscribeConnectivity, getConnectivity);

    if (status.online && !status.stale) return null;
    return (
        <div className="offline-banner" role="status">
            {/* one short line: Native.css moves the page down by exactly one line's height */}
            {status.online ? "Can't reach Zenith. Showing saved data." : "You're offline. Showing saved data."}
        </div>
    );
}

export default OfflineBanner;
