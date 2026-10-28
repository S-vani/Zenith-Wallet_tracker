import {useEffect, useState} from "react";
import {useLocation} from "react-router-dom";

let nextId = 0;

// A toast younger than this survives arriving on the login page: it's about the sign out that just happened
// ("Logged out", "Your session has expired"), while older ones ("Logged in", "Changes saved") are stale there
const FRESH_MS = 1500;
// how long a toast takes to slide out (Global.css toast-out)
const LEAVE_MS = 200;

function Toaster() {
    const [toasts, setToasts] = useState([]);
    const {pathname} = useLocation();

    // slides out first, then goes (a toast that just vanished looked like a glitch)
    const leave = (id) => {
        setToasts((current) => current.map((t) => (t.id === id ? {...t, leaving: true} : t)));
        setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), LEAVE_MS);
    };

    useEffect(() => {
        const onToast = (e) => {
            const id = ++nextId;
            const {message, type, duration} = e.detail;
            setToasts((current) => [...current, {id, message, type, duration, at: Date.now()}]);
            setTimeout(() => leave(id), duration);
        };
        // dispatched on log out, before the "Logged out" toast
        const onClear = () => setToasts([]);

        window.addEventListener("app:toast", onToast);
        window.addEventListener("app:toast-clear", onClear);
        return () => {
            window.removeEventListener("app:toast", onToast);
            window.removeEventListener("app:toast-clear", onClear);
        };
    }, []);

    // signing out from anywhere (account page, Face ID, an expired session) lands on /login
    useEffect(() => {
        if (pathname !== "/login") return;
        const cutoff = Date.now() - FRESH_MS;
        const timer = setTimeout(() => setToasts((current) => current.filter((t) => t.at >= cutoff)), 0);
        return () => clearTimeout(timer);
    }, [pathname]);


    return (
        <div className="toaster" role="status" aria-live="polite">
            {toasts.map((toast) => (
                <div key={toast.id} className={`toast ${toast.type}${toast.leaving ? " leaving" : ""}`}
                     style={{"--toast-ms": `${toast.duration ?? 3000}ms`}}>
                    <span className="toast-icon" aria-hidden="true">
                        {toast.type === "error" ? "!" : (
                            // the check draws itself
                            <svg viewBox="0 0 16 16" width="12" height="12">
                                <path d="M3 8.5l3 3 7-7" pathLength="1"/>
                            </svg>
                        )}
                    </span>
                    <span className="toast-message">{toast.message}</span>
                    <button className="toast-close" onClick={() => leave(toast.id)} aria-label="Dismiss">×</button>
                </div>
            ))}
        </div>
    );
}

export default Toaster;
