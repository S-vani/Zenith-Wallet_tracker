import {useEffect, useRef, useState} from "react";
import {useLocation} from "react-router-dom";
import {haptic} from "./haptics.js";
import {getConnectivity, whenRequestsSettle} from "./connectivity.js";
import {canPullToRefresh, MAX_SPIN_MS, MIN_SPIN_MS, pullAction} from "./refreshRules.js";
import {showToast} from "../utils/toast.js";

const TRIGGER = 70; // px of (damped) pull needed to refresh
const MAX = 110;

// touches that start on these are someone using a chart, form or scrolling list, not pulling the page
const IGNORE = ".recharts-wrapper, input, textarea, select, [role=dialog], .search-results-list svg";

// Resolves after `ms`.
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Pull down at the top of a page to reload it, like a native list. Only on the pages that reload (useRefreshKey):
// dashboard, holdings and transactions. The spinner turns until their requests have finished; offline, a toast
// says the saved data is shown instead of pretending to refresh.
function PullToRefresh() {
    const {pathname} = useLocation();
    const enabled = canPullToRefresh(pathname);
    const [pull, setPull] = useState(0);
    const [refreshing, setRefreshing] = useState(false);
    const start = useRef(null);
    const startX = useRef(0);
    const armed = useRef(false);
    const busy = useRef(false);

    useEffect(() => {
        if (!enabled) return;
        const refresh = async () => {
            if (pullAction(getConnectivity()) === "offline") {
                showToast("Offline — showing saved data", {type: "error"});
                return;
            }
            busy.current = true;
            setRefreshing(true);
            const started = Date.now();
            window.dispatchEvent(new Event("app:refresh"));
            await wait(120); // let the pages re-render and start their requests
            await Promise.race([whenRequestsSettle(), wait(MAX_SPIN_MS)]);
            await wait(Math.max(0, MIN_SPIN_MS - (Date.now() - started)));
            busy.current = false;
            setRefreshing(false);
        };
        const onStart = (e) => {
            // only from the very top, and not while a modal has locked the page
            if (window.scrollY > 0 || document.body.style.overflow === "hidden" || busy.current) return;
            if (e.target.closest?.(IGNORE)) return;
            start.current = e.touches[0].clientY;
            startX.current = e.touches[0].clientX;
            armed.current = false;
        };
        const onMove = (e) => {
            if (start.current === null) return;
            const dy = e.touches[0].clientY - start.current;
            // a mostly sideways swipe (e.g. across a chart or tabs) cancels the pull
            if (Math.abs(e.touches[0].clientX - startX.current) > Math.abs(dy)) {
                start.current = null;
                armed.current = false;
                setPull(0);
                return;
            }
            const distance = dy * 0.5; // resistance, like iOS
            if (distance <= 0) {
                setPull(0);
                return;
            }
            const next = Math.min(distance, MAX);
            if (next >= TRIGGER && !armed.current) {
                armed.current = true;
                haptic("medium"); // the "click" you feel when a pull will refresh
            } else if (next < TRIGGER) {
                armed.current = false;
            }
            setPull(next);
        };
        const onEnd = () => {
            if (start.current === null) return;
            start.current = null;
            if (armed.current) refresh();
            armed.current = false;
            setPull(0);
        };
        window.addEventListener("touchstart", onStart, {passive: true});
        window.addEventListener("touchmove", onMove, {passive: true});
        window.addEventListener("touchend", onEnd);
        window.addEventListener("touchcancel", onEnd);
        return () => {
            window.removeEventListener("touchstart", onStart);
            window.removeEventListener("touchmove", onMove);
            window.removeEventListener("touchend", onEnd);
            window.removeEventListener("touchcancel", onEnd);
            start.current = null;
        };
    }, [enabled]);

    if (!enabled) return null;

    const visible = refreshing || pull > 4;
    const offset = refreshing ? TRIGGER * 0.75 : pull * 0.75;
    return (
        <div className={`ptr${visible ? " visible" : ""}${refreshing ? " refreshing" : ""}`} aria-hidden="true"
             style={{transform: `translate(-50%, ${offset}px)`}}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"
                 style={refreshing ? undefined : {transform: `rotate(${pull * 3}deg)`}}>
                <path d="M20 12a8 8 0 1 1-2.34-5.66"/>
                <polyline points="20 4 20 9 15 9"/>
            </svg>
        </div>
    );
}

export default PullToRefresh;
