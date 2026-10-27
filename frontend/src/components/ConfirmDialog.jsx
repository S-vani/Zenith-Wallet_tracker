import {useEffect, useId, useRef} from "react";

// Small modal "are you sure?" box. Uses the browser's <dialog>, which keeps keyboard focus inside and closes on Esc
function ConfirmDialog({open, title, message, confirmLabel = "Confirm", onConfirm, onCancel}) {
    const ref = useRef(null);
    const titleId = useId();

    useEffect(() => {
        const dialog = ref.current;
        if (!dialog) return;
        if (open && !dialog.open) dialog.showModal?.();
        if (!open && dialog.open) dialog.close();
    }, [open]);

    // The app's Face ID lock (or "Update required" screen) is covering the page: cancel, because a modal dialog
    // would keep that screen's buttons from working (everything outside a modal <dialog> is inert)
    useEffect(() => {
        if (!open) return;
        const onCovered = () => onCancel();
        window.addEventListener("app:locked", onCovered);
        return () => window.removeEventListener("app:locked", onCovered);
    }, [open, onCancel]);

    return (
        <dialog
            ref={ref}
            className="confirm-dialog"
            aria-labelledby={titleId}
            onCancel={(e) => {
                e.preventDefault(); // Esc: let the parent decide, so `open` stays the single source of truth
                onCancel();
            }}
            onClick={(e) => {
                if (e.target === ref.current) onCancel(); // a tap on the backdrop
            }}
        >
            {open && (
                <div className="confirm-dialog-body">
                    <h2 id={titleId} className="confirm-dialog-title">{title}</h2>
                    {message && <p className="confirm-dialog-message">{message}</p>}
                    <div className="confirm-dialog-actions">
                        <button type="button" className="btn" onClick={onCancel} autoFocus>Cancel</button>
                        <button type="button" className="btn btn-primary" onClick={onConfirm}>{confirmLabel}</button>
                    </div>
                </div>
            )}
        </dialog>
    );
}

export default ConfirmDialog;
