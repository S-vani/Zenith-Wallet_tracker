import {useEffect, useState} from "react";
import {useLocation} from "react-router-dom";

let nextId = 0;

// A toast younger than this survives arriving on the login page: it's about the sign out that just happened
// ("Logged out", "Your session has expired"), while older ones ("Logged in", "Changes saved") are stale there
const FRESH_MS = 1500;

function Toaster() {
    const [toasts, setToasts] = useState([]);
    const {pathname} = useLocation();

    useEffect(() => {
        const onToast = (e) => {
            const id = ++nextId;
            const {message, type, duration} = e.detail;
            setToasts((current) => [...current, {id, message, type, at: Date.now()}]);
            setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), duration);
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

    const dismiss = (id) => setToasts((current) => current.filter((t) => t.id !== id));

    return (
        <div className="toaster" role="status" aria-live="polite">
            {toasts.map((toast) => (
                <div key={toast.id} className={`toast ${toast.type}`}>
                    <span className="toast-icon" aria-hidden="true">{toast.type === "error" ? "!" : "✓"}</span>
                    <span className="toast-message">{toast.message}</span>
                    <button className="toast-close" onClick={() => dismiss(toast.id)} aria-label="Dismiss">×</button>
                </div>
            ))}
        </div>
    );
}

export default Toaster;
