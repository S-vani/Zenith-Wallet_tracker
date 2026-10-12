import {useEffect, useState} from "react";

let nextId = 0;

function Toaster() {
    const [toasts, setToasts] = useState([]);

    useEffect(() => {
        const onToast = (e) => {
            const id = ++nextId;
            const {message, type, duration} = e.detail;
            setToasts((current) => [...current, {id, message, type}]);
            setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), duration);
        };

        window.addEventListener("app:toast", onToast);
        return () => window.removeEventListener("app:toast", onToast);
    }, []);

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
