import {useRef, useState} from "react";
import {searchCrypto, searchStock} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import TransactionSymbolList from "./TransactionSymbolList.jsx";
import TransactionSymbolItem from "./TransactionSymbolItem.jsx";
import TradeScan from "./TradeScan.jsx";
import {symbolSelection} from "./tradeForm.js";
import {scanNotes, scanPrefill, scanSymbol} from "./scanHelpers.js";

// onQueryChange lets the dialog know something was typed, so closing it by accident asks first.
// onSub(selection, scan): scan is {id, prefill, notes} when the trade came from a screenshot, else null.
function TransactionSymbolSearch({onSub, onQueryChange}) {
    const {currency} = useUser();
    const [type, setType] = useState("stock")
    const [symbol, setSymbol] = useState("");
    const [results, setResults] = useState(null);
    const [selectedSymbol, setSelectedSymbol] = useState(null);
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null);
    const searchId = useRef(0); // only the newest search may update the results
    const inputRef = useRef(null);
    // a scanned trade whose asset search didn't list: the asset the user then picks gets its prefill
    const [pendingScan, setPendingScan] = useState(null);
    const [scanKey, setScanKey] = useState(0); // remounts the scan box (cancels and clears it) on every pick
    const scanCount = useRef(0); // a new scan of the same asset still restarts the form with its values

    const scanned = (pending) => pending && {
        id: ++scanCount.current,
        prefill: scanPrefill(pending.trade, new Date()),
        notes: [...scanNotes(pending.trade, currency), ...pending.warnings],
    };

    const onSubSymbols = (data, selected) => {
        onSub(data, scanned(pendingScan));
        setPendingScan(null);
        setScanKey((k) => k + 1);
        setResults(null)
        setSelectedSymbol(selected)
    }

    // the screenshot's asset was found: straight to the form, as if it had been searched and picked
    const scanFound = (result, trade, warnings) => {
        searchId.current += 1; // a search still running mustn't put its results back over the form
        setLoading(false);
        setError(null);
        setType(result.type ?? type);
        setPendingScan(null);
        onSub(symbolSelection(result), scanned({trade, warnings}));
        setScanKey((k) => k + 1);
        setResults(null);
        setSelectedSymbol(result);
    };

    // not listed under that exact symbol: put it in the search box so the user can search and pick it
    const scanNotFound = (trade, warnings) => {
        searchId.current += 1;
        setLoading(false);
        setError(null);
        setResults(null);
        setType(trade.asset_type === "crypto" ? "crypto" : "stock");
        changeQuery(scanSymbol(trade));
        setPendingScan({trade, warnings});
        inputRef.current?.focus();
    };

    const changeQuery = (text) => {
        setSymbol(text);
        onQueryChange?.(text);
    };

    const changeType = (newType) => {
        searchId.current += 1;
        setLoading(false);
        setType(newType);
        changeQuery("");  // a stock ticker typed before the switch isn't a coin (and vice versa)
        setResults(null);
        setError(null);
        setPendingScan(null); // the scanned trade was a stock (or a coin); this is a different search now
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!symbol.trim()) return;

        const id = ++searchId.current;
        setLoading(true)
        setError(null);
        try {
            const data = type === "stock" ? await searchStock(symbol) : await searchCrypto(symbol);
            if (id === searchId.current) setResults(data)
        } catch (err) {
            if (id === searchId.current) setError(err.message);
        } finally {
            if (id === searchId.current) setLoading(false)
        }
    };

    return (
        <div className="transaction-symbol-wrapper">
            <div className="segmented" role="group" aria-label="Asset type">
                <button className={type === "stock" ? "active" : ""} aria-pressed={type === "stock"}
                        onClick={() => changeType("stock")}>
                    Stock
                </button>
                <button className={type === "crypto" ? "active" : ""} aria-pressed={type === "crypto"}
                        onClick={() => changeType("crypto")}>
                    Crypto
                </button>
            </div>

            <form className="symbol-search-form" onSubmit={handleSubmit} role="search">
                {/* placeholder short enough to fit beside the Search button at 375px; the label says what's searched */}
                <input
                    ref={inputRef}
                    className="symbol-search-input"
                    name="symbol"
                    type="search"
                    aria-label={`Search ${type} symbols`}
                    placeholder={type === "stock" ? "e.g. AAPL, SHOP.TO" : "e.g. BTC, ETH"}
                    value={symbol}
                    onChange={(e) => changeQuery(e.target.value)}
                    autoComplete="off"
                    autoFocus
                />
                <button className="btn btn-primary" type="submit" disabled={loading || !symbol.trim()}>
                    {loading ? "Searching…" : "Search"}
                </button>
            </form>

            {error && <p className="alert-error" role="alert">{error}</p>}

            <TradeScan key={scanKey} onFound={scanFound} onNotFound={scanNotFound}/>

            {results && (
                results.length > 0 ? (
                    <TransactionSymbolList data={results} onSub={onSubSymbols}/>
                ) : (
                    <p className="state-message">No matches for “{symbol}”. Check the symbol and try again.</p>
                )
            )}

            {!results && selectedSymbol !== null && (
                <TransactionSymbolItem data={selectedSymbol} selected/>
            )}
        </div>
    );
}

export default TransactionSymbolSearch
