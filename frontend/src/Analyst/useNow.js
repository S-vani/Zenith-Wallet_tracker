import {useEffect, useState} from "react";

// Current time that re-renders every `intervalMs`, plus once exactly at `wakeAt` (e.g. when a cooldown ends)
// so "3 min ago" and countdowns stay correct without a parent re-render
export default function useNow(intervalMs = 15000, wakeAt = null) {
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), intervalMs);
        return () => clearInterval(id);
    }, [intervalMs]);

    useEffect(() => {
        if (!wakeAt) return undefined;
        // catch up right away (a new report just arrived), then tick again when the time is reached
        const sync = setTimeout(() => setNow(Date.now()), 0);
        const delay = wakeAt - Date.now();
        const id = delay > 0 && delay < 24 * 60 * 60 * 1000 ? setTimeout(() => setNow(Date.now()), delay + 50) : null;
        return () => {
            clearTimeout(sync);
            if (id) clearTimeout(id);
        };
    }, [wakeAt]);

    return now;
}
