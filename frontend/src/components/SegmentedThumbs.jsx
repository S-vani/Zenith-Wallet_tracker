import {useEffect} from "react";

// Gives every segmented control (.segmented: chart ranges, allocation tabs, Stock / Crypto...) a pill that slides to
// the chosen option, the way native segmented controls move, instead of the highlight jumping. One watcher for the
// whole app rather than a change to each control: it places the pill (.segmented::before, Global.css) under the
// button that has `.active` whenever a class or the page changes. The Buy / Sell picker keeps its own green / red.
// The first placement doesn't slide; under prefers-reduced-motion nothing slides. Renders nothing.
function place(group) {
    const active = group.querySelector(":scope > button.active");
    if (!active || group.querySelector(":scope > button.buy, :scope > button.sell")) {
        if (group.classList.contains("has-thumb")) group.classList.remove("has-thumb", "thumb-ready");
        return;
    }
    group.style.setProperty("--thumb-x", `${active.offsetLeft}px`);
    group.style.setProperty("--thumb-y", `${active.offsetTop}px`);
    group.style.setProperty("--thumb-w", `${active.offsetWidth}px`);
    group.style.setProperty("--thumb-h", `${active.offsetHeight}px`);
    if (!group.classList.contains("has-thumb")) {
        group.classList.add("has-thumb");
        // slide only from the next change on
        requestAnimationFrame(() => requestAnimationFrame(() => group.classList.add("thumb-ready")));
    }
}

// Watches the page for segmented controls and keeps their pills in place.
function SegmentedThumbs() {
    useEffect(() => {
        let queued = false;
        const update = () => {
            queued = false;
            document.querySelectorAll(".segmented").forEach(place);
        };
        const schedule = () => {
            if (queued) return;
            queued = true;
            requestAnimationFrame(update);
        };
        // only class and structure changes: the style properties set above don't trigger it, so it can't loop
        const observer = new MutationObserver(schedule);
        observer.observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["class"]});
        window.addEventListener("resize", schedule);
        schedule();
        return () => {
            observer.disconnect();
            window.removeEventListener("resize", schedule);
        };
    }, []);
    return null;
}

export default SegmentedThumbs;
