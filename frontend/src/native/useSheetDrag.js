import {useEffect, useRef} from "react";
import {isNative} from "./platform.js";

// how far (px) a sheet has to be pulled down before letting go closes it
const DISMISS_PX = 120;

// App only: an open sheet (the add-trade box) follows the finger down from its top, and pulled far enough it closes
// through `onDismiss` (which still asks "Discard this trade?" when something was entered), like an iOS sheet. A
// shorter pull springs back. Starts from the sheet's header, or anywhere once the sheet is scrolled to its top.
export default function useSheetDrag(boxRef, open, onDismiss) {
    const dismissRef = useRef(onDismiss);
    useEffect(() => {
        dismissRef.current = onDismiss;
    });

    useEffect(() => {
        const box = boxRef.current;
        if (!isNative || !open || !box) return;
        let startY = null;
        let dy = 0;
        const onStart = (e) => {
            if (box.scrollTop > 0 && !e.target.closest?.(".modal-header")) return; // scrolling the form back up
            if (e.target.closest?.("input, textarea, select, .recharts-wrapper")) return; // typing, or using a chart
            startY = e.touches[0].clientY;
            dy = 0;
        };
        const onMove = (e) => {
            if (startY === null) return;
            dy = Math.max(0, e.touches[0].clientY - startY);
            if (dy === 0) return;
            box.style.transition = "none";
            box.style.transform = `translateY(${dy}px)`;
        };
        const onEnd = () => {
            if (startY === null) return;
            startY = null;
            box.style.transition = "transform 0.32s cubic-bezier(0.32, 0.72, 0, 1)";
            box.style.transform = "";
            if (dy > DISMISS_PX) dismissRef.current();
            dy = 0;
        };
        box.addEventListener("touchstart", onStart, {passive: true});
        box.addEventListener("touchmove", onMove, {passive: true});
        box.addEventListener("touchend", onEnd);
        box.addEventListener("touchcancel", onEnd);
        return () => {
            box.removeEventListener("touchstart", onStart);
            box.removeEventListener("touchmove", onMove);
            box.removeEventListener("touchend", onEnd);
            box.removeEventListener("touchcancel", onEnd);
        };
    }, [boxRef, open]);
}
