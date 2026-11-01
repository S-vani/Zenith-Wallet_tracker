import {useEffect, useId, useRef, useState} from "react";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import {scanTradeScreenshot, searchCrypto, searchStock} from "../services/api.js";
import {
    hasScanConsent, pickSearchMatch, saveScanConsent, scanSearchQuery, scanSymbol, scanTradeDay, scanTradeLabel,
    shrinkImage,
} from "./scanHelpers.js";

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

// "Scan a screenshot": a trade confirmation is read on the server (Google Gemini) and handed back as trades. One
// trade goes straight to the add form once its asset is found in search; several are listed to pick from.
// Nothing is saved here. onFound(searchResult, trade, warnings) when the asset is known; onNotFound(trade,
// warnings) when search doesn't list it, so the search box can take over.
function TradeScan({onFound, onNotFound}) {
    const inputRef = useRef(null);
    const buttonRef = useRef(null);
    const choicesRef = useRef(null);
    const controllerRef = useRef(null);
    const choicesId = useId();
    const hintId = useId();
    const [asking, setAsking] = useState(false); // the consent question is showing
    const [busy, setBusy] = useState(null); // what's happening, e.g. "Reading your screenshot…"
    const [error, setError] = useState(null);
    const [choices, setChoices] = useState(null); // {trades, warnings} when the screenshot has several trades

    // closing the dialog (or picking a search result, which remounts this) cancels a scan still in progress
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
        if (hasScanConsent()) inputRef.current?.click();
        else setAsking(true);
    };

    // still inside the click on "Continue", so the browser lets it open the photo picker
    const agree = () => {
        saveScanConsent();
        setAsking(false);
        inputRef.current?.click();
    };

    const freshController = () => {
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;
        return controller;
    };

    // finds the scanned asset in search, the same way the user would, so the form gets a real listing to save
    const lookUp = async (trade, warnings, controller) => {
        setBusy(`Looking up ${scanSymbol(trade)}…`);
        const search = trade.asset_type === "crypto" ? searchCrypto : searchStock;
        const results = await search(scanSearchQuery(trade), {signal: controller.signal});
        if (controller.signal.aborted) return;
        const match = pickSearchMatch(results, trade);
        setBusy(null);
        if (match) {
            onFound(match, trade, warnings);
        } else {
            setError(`Couldn't find ${scanSymbol(trade)}. Search for it above.`);
            onNotFound(trade, warnings);
        }
    };

    const fail = (err, controller) => {
        if (err?.name === "AbortError" || controller.signal.aborted) return; // closed or replaced: say nothing
        setBusy(null);
        setError(err?.message ?? "Couldn't read the screenshot. Please try again, or enter the trade yourself.");
    };

    const read = async (file) => {
        const controller = freshController();
        setError(null);
        setChoices(null);
        setBusy("Reading your screenshot…");
        try {
            const image = await shrinkImage(file);
            if (controller.signal.aborted) return;
            const {trades, warnings} = await scanTradeScreenshot(image, {signal: controller.signal});
            if (controller.signal.aborted) return;
            if (trades.length === 0) {
                throw new Error("Couldn't find a buy or sell in this screenshot. Enter the trade yourself.");
            }
            if (trades.length === 1) {
                await lookUp(trades[0], warnings, controller);
            } else {
                setBusy(null);
                setChoices({trades, warnings});
            }
        } catch (err) {
            fail(err, controller);
        }
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

    return (
        <div className="trade-scan" aria-busy={Boolean(busy)}>
            <div className="trade-scan-row">
                <button type="button" className="btn btn-secondary trade-scan-button" ref={buttonRef}
                        onClick={start} disabled={Boolean(busy)} aria-describedby={hintId}>
                    {busy ? <span className="trade-scan-spinner" aria-hidden="true"/> : <ScanIcon/>}
                    {busy ?? "Scan a screenshot"}
                </button>
                <p className="trade-scan-hint" id={hintId}>
                    Fill this in from a trade confirmation. You check it before it's saved.
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

            {/* announced while it reads; the button's own text changes too, but a disabled button isn't read out */}
            <span className="visually-hidden" role="status">{busy ?? ""}</span>

            {error && <p className="alert-error" role="alert">{error}</p>}

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
                    title="Read a screenshot with AI?"
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
