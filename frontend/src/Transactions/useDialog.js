import {useEffect, useRef} from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
    'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Toasts and the offline banner must keep announcing, and the app's own lock screen must stay usable
const KEEP_REACHABLE = '[aria-live], [role="status"], [role="alert"], [role="dialog"], script, style';

function focusables(root) {
    // skip hidden ones (e.g. the price chart's controls while it's collapsed)
    return [...root.querySelectorAll(FOCUSABLE)].filter((el) => el.getClientRects().length > 0);
}

// Make everything around the dialog inert (page, nav, tab bar) so keyboard and screen readers stay inside it.
// Returns a function that undoes exactly what it changed.
function inertOutside(dialog) {
    const changed = [];
    for (let node = dialog; node.parentElement && node.parentElement !== document.body; node = node.parentElement) {
        for (const sibling of node.parentElement.children) {
            if (sibling === node || sibling.inert || sibling.matches(KEEP_REACHABLE)) continue;
            sibling.inert = true;
            changed.push(sibling);
        }
    }
    return () => changed.forEach((el) => {
        el.inert = false;
    });
}

// Modal dialog behaviour: Tab stays inside, Esc closes, the rest of the page is inert, and on close focus goes
// back to whatever opened it (or `returnFocusRef` if that element is gone, e.g. the empty-state button).
export default function useDialog(dialogRef, open, onClose, returnFocusRef) {
    const onCloseRef = useRef(onClose);
    useEffect(() => {
        onCloseRef.current = onClose;
    });

    useEffect(() => {
        const dialog = dialogRef.current;
        if (!open || !dialog) return;

        const opener = document.activeElement;
        const fallback = returnFocusRef?.current; // the sidebar button, which stays on the page
        const undoInert = inertOutside(dialog);
        if (!dialog.contains(document.activeElement)) {
            (focusables(dialog)[0] ?? dialog).focus();
        }

        const onKeyDown = (e) => {
            if (e.key === "Escape") {
                onCloseRef.current();
                return;
            }
            if (e.key !== "Tab") return;

            const items = focusables(dialog);
            if (items.length === 0) {
                e.preventDefault();
                return;
            }
            const first = items[0];
            const last = items[items.length - 1];
            const inside = dialog.contains(document.activeElement);
            if (e.shiftKey && (!inside || document.activeElement === first)) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && (!inside || document.activeElement === last)) {
                e.preventDefault();
                first.focus();
            }
        };
        document.addEventListener("keydown", onKeyDown);

        return () => {
            document.removeEventListener("keydown", onKeyDown);
            undoInert();
            const target = opener?.isConnected && opener !== document.body ? opener : fallback;
            target?.focus?.();
        };
    }, [open, dialogRef, returnFocusRef]);
}
