import {isNative} from "./platform.js";

// App only: big amounts (CA$98,765,432.10) shrink to fit their card, like a native label with "adjusts font size
// to fit width", instead of breaking in the middle of the number. Native.css turns off the website's
// break-anywhere wrapping for these; only an amount still too wide at the smallest size wraps (class fit-wrap).
const SELECTOR = ".stat-value, .holding-item > span, .holdings-totals-row > span, .symbol-price, .symbol-change, " +
    ".price-paid";
const MIN_SCALE = 0.6;

const fitted = new WeakMap(); // element -> "text|width" it was last fitted for, so unchanged ones are skipped
// bumped when the iPhone's Text Size changes: the text and width stay the same, but every fit is out of date
let textSizeGeneration = 0;

// The font size that makes content of naturalWidth fit in availableWidth, never below MIN_SCALE of the base size.
// null = it already fits. Pure, for the tests.
export function fittedSize({baseSize, naturalWidth, availableWidth}) {
    if (!availableWidth || naturalWidth <= availableWidth + 1) return null;
    return Math.max(Math.floor(baseSize * (availableWidth / naturalWidth) * 10) / 10, baseSize * MIN_SCALE);
}

function fit(element) {
    const width = element.clientWidth;
    const signature = `${textSizeGeneration}|${element.textContent}|${width}`;
    if (!width || fitted.get(element) === signature) return;
    fitted.set(element, signature);

    element.style.fontSize = ""; // measure at the stylesheet's size
    element.classList.remove("fit-wrap");
    const size = fittedSize({
        baseSize: parseFloat(getComputedStyle(element).fontSize),
        naturalWidth: element.scrollWidth,
        availableWidth: element.clientWidth,
    });
    if (size === null) return;
    element.style.fontSize = `${size}px`;
    if (element.scrollWidth > element.clientWidth + 1) element.classList.add("fit-wrap");
}

export function watchNumbers() {
    if (!isNative || typeof MutationObserver === "undefined") return;
    let queued = false;
    const run = () => {
        queued = false;
        document.querySelectorAll(SELECTOR).forEach(fit);
    };
    const schedule = () => {
        if (queued) return;
        queued = true;
        requestAnimationFrame(run);
    };
    // style / class changes made here are attribute changes, which aren't observed, so this can't loop
    new MutationObserver(schedule).observe(document.body, {childList: true, subtree: true, characterData: true});
    window.addEventListener("resize", schedule);
    window.addEventListener("app:text-size", () => {
        textSizeGeneration += 1;
        schedule();
    });
}
