import {useRef, useState} from "react";
import {searchCrypto, searchStock} from "../services/api.js";
import TransactionSymbolList from "./TransactionSymbolList.jsx";
import TransactionSymbolItem from "./TransactionSymbolItem.jsx";

function TransactionSymbolSearch({onSub}) {
    const [type, setType] = useState("stock")
    const [symbol, setSymbol] = useState("");
    const [results, setResults] = useState(null);
    const [selectedSymbol, setSelectedSymbol] = useState(null);
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null);
    const searchId = useRef(0); // only the newest search may update the results

    const onSubSymbols = (data, selected) => {
        onSub(data);
        setResults(null)
        setSelectedSymbol(selected)
    }

    const changeType = (newType) => {
        searchId.current += 1;
        setLoading(false);
        setType(newType);
        setResults(null);
        setError(null);
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
                <input
                    className="symbol-search-input"
                    name="symbol"
                    type="search"
                    aria-label={`Search ${type} symbols`}
                    placeholder={type === "stock" ? "Search stocks, e.g. AAPL, NVDA" : "Search crypto, e.g. BTC, ETH"}
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    autoComplete="off"
                    autoFocus
                />
                <button className="btn btn-primary" type="submit" disabled={loading || !symbol.trim()}>
                    {loading ? "Searching…" : "Search"}
                </button>
            </form>

            {error && <p className="alert-error" role="alert">{error}</p>}

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
