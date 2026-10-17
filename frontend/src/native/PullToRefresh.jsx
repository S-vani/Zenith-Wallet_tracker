import {useEffect, useRef, useState} from "react";
import {haptic} from "./haptics.js";

const TRIGGER = 70; // px of (damped) pull needed to refresh
const MAX = 110;

// Pull down at the top of a page to reload it, like a native list. Pages listen through useRefreshKey().
function PullToRefresh() {
    const [pull, setPull] = useState(0);
    const [refreshing, setRefreshing] = useState(false);
    const start = useRef(null);
    const armed = useRef(false);

    useEffect(() => {
        const onStart = (e) => {
            // only from the very top, and not while a modal has locked the page
            if (window.scrollY > 0 || document.body.style.overflow === "hidden" || refreshing) return;
            start.current = e.touches[0].clientY;
            armed.current = false;
        };
        const onMove = (e) => {
            if (start.current === null) return;
            const distance = (e.touches[0].clientY - start.current) * 0.5; // resistance, like iOS
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
            if (armed.current) {
                setRefreshing(true);
                window.dispatchEvent(new Event("app:refresh"));
                setTimeout(() => setRefreshing(false), 900);
            }
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
        };
    }, [refreshing]);

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
