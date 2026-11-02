import {useEffect, useId, useRef, useState} from "react";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import {getScanOptions, scanTradeFields, scanTradeScreenshot, searchCrypto, searchStock} from "../services/api.js";
import {
    hasScanConsent, pickSearchMatch, saveScanConsent, scanSearchQuery, scanSymbol, scanTradeDay, scanTradeLabel,
    shrinkImage,
} from "./scanHelpers.js";
import {readScreenshotText} from "./textReader.js";
import {parseTradeText} from "./tradeTextParser.js";

// A photo with a plus: "add from an image"
function ScanIcon() {
    return (
        <svg className="trade-scan-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M20 13v5.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13A1.5 1.5 0 0 1 5.5 4H11"/>
            <circle cx="9" cy="9.5" r="1.5"/>
            <path d="m4.5 18 4.5-4.5 3 3 2.5-2.5L20 19"/>
            <path d="M18 3v6M15 6h6"/>
        </svg>
    );
}

// Keys pressed in the consent question stay with it: the add-trade dialog behind listens on the document for Esc
// (which would close the whole dialog) and Tab (its focus trap doesn't know about the native modal on top)
const stopDialogKeys = (e) => {
    if (e.key === "Escape" || e.key === "Tab") e.stopPropagation();
};

const READING = "Reading your screenshot on this device…";
const GETTING_READY = "Getting the text reader ready…";
const NOT_FOUND = "Couldn't read a trade from this screenshot.";

// "Scan a screenshot": the text on a trade confirmation is read on this device (Apple Vision in the app, Tesseract
// on the website, textReader.js), turned into trade fields by rules (tradeTextParser.js), and only those fields go
// to the server to be checked and converted (POST /transactions/scan/fields). The image never leaves the device,
// so there's no consent question for this. When nothing is found and the server has the optional AI reading on,
// "Try AI reading" sends the same image to Google Gemini, after asking.
// One trade goes straight to the add form once its asset is found in search; several are listed to pick from.
// Nothing is saved here. onFound(searchResult, trade, warnings) when the asset is known; onNotFound(trade,
// warnings) when search doesn't list it, so the search box can take over.
function TradeScan({onFound, onNotFound}) {
    const inputRef = useRef(null);
    const buttonRef = useRef(null);
    const choicesRef = useRef(null);
    const controllerRef = useRef(null);
    const imageRef = useRef(null); // the shrunk screenshot, kept for "Try AI reading"
    const optionsRef = useRef(null); // the server's scan options, asked for while the text is read
    const choicesId = useId();
    const hintId = useId();
    const [asking, setAsking] = useState(false); // the AI consent question is showing
    const [busy, setBusy] = useState(null); // what's happening, e.g. "Reading your screenshot on this device…"
    const [progress, setProgress] = useState(undefined); // undefined: no bar; null: no known share; else 0..1
    const [error, setError] = useState(null);
    const [offerAi, setOfferAi] = useState(false); // "Try AI reading" after the device found nothing
    const [choices, setChoices] = useState(null); // {trades, warnings} when the screenshot has several trades

    // closing the dialog (or picking a search result, which remounts this) cancels a scan still in progress; the
    // text reader stops with it
    useEffect(() => () => controllerRef.current?.abort(), []);

    // the button is disabled while reading, so focus falls to the page; bring it back to what comes next
    useEffect(() => {
        if (busy) return;
        const active = document.activeElement;
        if (active && active !== document.body) return;
        (choices ? choicesRef.current : buttonRef.current)?.focus();
    }, [busy, choices]);

    const start = () => {
        setError(null);
        setOfferAi(false);
        inputRef.current?.click();
    };

    const freshController = () => {
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;
        return controller;
    };

    const cancel = () => {
        controllerRef.current?.abort();
        setBusy(null);
        setProgress(undefined);
    };

    const working = (text, share = undefined) => {
        setBusy(text);
        setProgress(share);
    };

    // finds the scanned asset in search, the same way the user would, so the form gets a real listing to save
    const lookUp = async (trade, warnings, controller) => {
        working(`Looking up ${scanSymbol(trade)}…`);
        const search = trade.asset_type === "crypto" ? searchCrypto : searchStock;
        const results = await search(scanSearchQuery(trade), {signal: controller.signal});
        if (controller.signal.aborted) return;
        const match = pickSearchMatch(results, trade);
        working(null);
        if (match) {
            onFound(match, trade, warnings);
        } else {
            setError(`Couldn't find ${scanSymbol(trade)}. Search for it above.`);
            onNotFound(trade, warnings);
        }
    };

    // one trade to the form, several to pick from
    const show = async ({trades, warnings}, controller) => {
        if (trades.length === 1) {
            await lookUp(trades[0], warnings, controller);
        } else {
            working(null);
            setChoices({trades, warnings});
        }
    };

    const fail = (err, controller) => {
        if (err?.name === "AbortError" || controller.signal.aborted) return; // closed or replaced: say nothing
        working(null);
        setError(err?.message ?? "Couldn't read the screenshot. Please try again, or enter the trade yourself.");
    };

    // nothing usable on the screenshot: say so, and offer the AI reading only when the server has it on
    const notFound = async (message, controller) => {
        working(null);
        setError(message);
        const {ai} = await (optionsRef.current ?? getScanOptions());
        if (!controller.signal.aborted) setOfferAi(ai && Boolean(imageRef.current));
    };

    const read = async (file) => {
        const controller = freshController();
        setError(null);
        setOfferAi(false);
        setChoices(null);
        imageRef.current = null;
        working(READING);
        try {
            const image = await shrinkImage(file);
            if (controller.signal.aborted) return;
            imageRef.current = image;
            optionsRef.current = getScanOptions({signal: controller.signal}); // never throws: {ai: false} then

            let lines;
            try {
                ({lines} = await readScreenshotText(image, {
                    signal: controller.signal,
                    onProgress: ({phase, progress: share}) => {
                        if (controller.signal.aborted) return;
                        if (phase === "loading") working(GETTING_READY, null);
                        else working(READING, share);
                    },
                }));
            } catch (err) {
                if (err?.name === "AbortError" || controller.signal.aborted) return;
                await notFound(err?.message ?? NOT_FOUND, controller);
                return;
            }
            if (controller.signal.aborted) return;

            const {trades, moreTrades} = parseTradeText(lines, {now: new Date()});
            if (trades.length === 0) {
                await notFound(NOT_FOUND, controller);
                return;
            }
            working("Checking the trade…");
            let result;
            try {
                result = await scanTradeFields(trades, {signal: controller.signal, moreTrades});
            } catch (err) {
                if (err?.status !== 422) throw err;
                if (!controller.signal.aborted) await notFound(NOT_FOUND, controller);
                return;
            }
            if (controller.signal.aborted) return;
            // so the prefilled form can say where its values came from
            const onDevice = result.trades.map((trade) => ({...trade, onDevice: true}));
            if (onDevice.length === 0) {
                await notFound(NOT_FOUND, controller);
                return;
            }
            await show({trades: onDevice, warnings: result.warnings}, controller);
        } catch (err) {
            fail(err, controller);
        }
    };

    // the optional AI reading of the same image, after a clear yes (App Store guideline 5.1.2(i)), asked once per
    // device
    const readWithAi = async () => {
        const image = imageRef.current;
        if (!image) return;
        const controller = freshController();
        setError(null);
        setOfferAi(false);
        working("Reading your screenshot with AI…");
        try {
            const result = await scanTradeScreenshot(image, {signal: controller.signal});
            if (controller.signal.aborted) return;
            if (result.trades.length === 0) {
                throw new Error("Couldn't find a buy or sell in this screenshot. Enter the trade yourself.");
            }
            await show(result, controller);
        } catch (err) {
            fail(err, controller);
        }
    };

    const tryAi = () => {
        if (hasScanConsent()) readWithAi();
        else setAsking(true);
    };

    const agree = () => {
        saveScanConsent();
        setAsking(false);
        readWithAi();
    };

    const pick = async (trade) => {
        const controller = freshController();
        setError(null);
        try {
            await lookUp(trade, choices?.warnings ?? [], controller);
        } catch (err) {
            fail(err, controller);
        }
    };

    const percent = progress == null ? null : Math.round(progress * 100);

    return (
        <div className="trade-scan" aria-busy={Boolean(busy)}>
            <div className="trade-scan-row">
                <button type="button" className="btn btn-secondary trade-scan-button" ref={buttonRef}
                        onClick={start} disabled={Boolean(busy)} aria-describedby={hintId}>
                    {busy ? <span className="trade-scan-spinner" aria-hidden="true"/> : <ScanIcon/>}
                    {busy ?? "Scan a screenshot"}
                </button>
                <p className="trade-scan-hint" id={hintId}>
                    Read on your device. Only the trade details are sent.
                </p>
            </div>

            {/* image/* lets iPhones offer Photo Library, Take Photo and Choose File, in the app's web view too.
                `hidden` keeps it out of the dialog's Tab order; it's opened from the button above. */}
            <input ref={inputRef} type="file" accept="image/*" hidden tabIndex={-1}
                   onChange={(e) => {
                       const file = e.target.files?.[0];
                       e.target.value = ""; // so picking the same screenshot again still counts as a change
                       if (file) read(file);
                   }}/>

            {/* the first scan on the website downloads the text reader (a few MB, once): a bar so it doesn't look
                stuck. Without a known share it's the browser's moving (indeterminate) bar. */}
            {busy && progress !== undefined && (
                <div className="trade-scan-progress">
                    <progress max={100} value={percent ?? undefined} aria-label={busy}/>
                    <button type="button" className="inline-link" onClick={cancel}>Cancel</button>
                </div>
            )}

            {/* announced while it reads; the button's own text changes too, but a disabled button isn't read out */}
            <span className="visually-hidden" role="status">{busy ?? ""}</span>

            {error && (
                <div className="trade-scan-failed">
                    <p className="alert-error" role="alert">{error}</p>
                    {offerAi && (
                        <button type="button" className="btn btn-secondary trade-scan-ai" onClick={tryAi}>
                            Try AI reading
                        </button>
                    )}
                </div>
            )}

            {choices && (
                <div className="trade-scan-choices" role="group" aria-labelledby={choicesId}>
                    <p id={choicesId} ref={choicesRef} tabIndex={-1}>
                        This screenshot has {choices.trades.length} trades. Pick the one to add:
                    </p>
                    <ul>
                        {choices.trades.map((trade, i) => {
                            const day = scanTradeDay(trade);
                            return (
                                <li key={i}>
                                    <button type="button"
                                            className={`trade-scan-choice ${trade.action === "SELL" ? "sell" : "buy"}`}
                                            disabled={Boolean(busy)} onClick={() => pick(trade)}>
                                        <span className="trade-scan-choice-label">{scanTradeLabel(trade)}</span>
                                        {day && <span className="trade-scan-choice-date">{day}</span>}
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                    {choices.warnings.map((warning) => (
                        <p className="trade-scan-warning" key={warning}>{warning}</p>
                    ))}
                </div>
            )}

            <div onKeyDown={stopDialogKeys}>
                <ConfirmDialog
                    open={asking}
                    title="Read the screenshot with AI?"
                    message={"Your screenshot is sent to Google's Gemini AI to read the trade. Zenith doesn't keep " +
                        "the image. Crop out anything you'd rather not share, like account numbers."}
                    confirmLabel="Continue"
                    onConfirm={agree}
                    onCancel={() => setAsking(false)}
                />
            </div>
        </div>
    );
}

export default TradeScan;
