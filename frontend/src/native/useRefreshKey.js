import {useEffect, useState} from "react";

// A number that goes up whenever the app asks pages to reload their data ("app:refresh": pull to refresh, or
// coming back to the app after a while). Add it to a data-loading effect's dependencies.
// On the website the event never fires, so the value stays 0 and nothing changes.
export default function useRefreshKey() {
    const [key, setKey] = useState(0);

    useEffect(() => {
        const bump = () => setKey((k) => k + 1);
        window.addEventListener("app:refresh", bump);
        return () => window.removeEventListener("app:refresh", bump);
    }, []);

    return key;
}
