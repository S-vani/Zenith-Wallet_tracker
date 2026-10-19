import "../css/Search.css"
import {useRef, useState} from "react";
import {searchCrypto, searchStock} from "../services/api.js";
import SearchResults from "../Search/SearchResults.jsx"
import usePageTitle from "../utils/usePageTitle.js";

// tappable examples shown before the first search
const EXAMPLES = {
    stock: ["AAPL", "NVDA", "MSFT", "VOO"],
    crypto: ["BTC", "ETH", "SOL", "USDT"],
};

const MAX_QUERY_LENGTH = 20; // the backend rejects longer searches

function SearchPage() {
    usePageTitle("Search");

    const [searchSymbol, setSearchSymbol] = useState({"symbol": "", "type": "stock"});
    const [searchResults, setSearchResults] = useState(null) // hold the search results, null until the first search
    const [lastQuery, setLastQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const searchId = useRef(0); // only the newest search may update the page

    function setType(type) {
        searchId.current += 1;
        setLoading(false);
        setSearchSymbol({...searchSymbol, type});
        setSearchResults(null);
        setError(null);
        // the typed text is kept, so search it again as the new type
        if (searchSymbol.symbol.trim()) runSearch(searchSymbol.symbol.trim(), type);
    }

    async function searchBarSubmit(e) {
        e.preventDefault();
        const query = searchSymbol.symbol.trim();
        if (!query) return;
        runSearch(query, searchSymbol.type);
    }

    function searchExample(symbol) {
        setSearchSymbol({...searchSymbol, symbol});
        runSearch(symbol, searchSymbol.type);
    }

    async function runSearch(query, type) {

        const id = ++searchId.current;
        setLoading(true);
        setError(null);
        try {
            const data = type === "stock" ? await searchStock(query) : await searchCrypto(query);
            if (id !== searchId.current) return;
            setSearchResults(data);
            setLastQuery(query);
        } catch (err) {
            if (id === searchId.current) setError(err.message);
        } finally {
            if (id === searchId.current) setLoading(false);
        }
    }

    return (
        <div className="app-page search-page-wrapper">
            <header className="search-header">
                <h1 className="page-headers">Search</h1>
                <p className="page-subtitle">Look up recent prices for US stocks and crypto.</p>
            </header>

            <div className="search-area">
                <div className="segmented" role="group" aria-label="Asset type">
                    <button
                        className={searchSymbol.type === "stock" ? "active" : ""}
                        aria-pressed={searchSymbol.type === "stock"}
                        onClick={() => setType("stock")}>
                        Stock
                    </button>
                    <button
                        className={searchSymbol.type === "crypto" ? "active" : ""}
                        aria-pressed={searchSymbol.type === "crypto"}
                        onClick={() => setType("crypto")}>
                        Crypto
                    </button>
                </div>
                <form className="search-form" role="search" onSubmit={searchBarSubmit}>
                    <svg className="search-form-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                        <circle cx="11" cy="11" r="7"/>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                    </svg>
                    <input
                        value={searchSymbol.symbol}
                        onChange={(e) => setSearchSymbol({...searchSymbol, symbol: e.target.value})}
                        className="search-bar"
                        type="search"
                        aria-label={`Search ${searchSymbol.type}`}
                        placeholder={searchSymbol.type === "stock" ? "Search a ticker, e.g. AAPL" : "Search a coin, e.g. BTC"}
                        autoComplete="off"
                        maxLength={MAX_QUERY_LENGTH}
                        autoFocus
                    />
                    <button className="btn btn-primary" type="submit" disabled={!searchSymbol.symbol.trim()}>
                        {loading ? "Searching…" : "Search"}
                    </button>
                </form>
            </div>

            {error && <p className="alert-error search-error" role="alert">{error}</p>}

            {!searchResults && !loading && !error && (
                <div className="search-intro">
                    <strong>Find a {searchSymbol.type === "stock" ? "stock or ETF" : "coin"}</strong>
                    <p>
                        Search by ticker or name, then tap a result to open its price chart and a Market Analyst
                        report.
                    </p>
                    <div className="search-examples" role="group" aria-label="Example searches">
                        {EXAMPLES[searchSymbol.type].map((symbol) => (
                            <button key={symbol} type="button" className="search-example"
                                    onClick={() => searchExample(symbol)}>
                                {symbol}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {searchResults && (
                searchResults.length > 0 ? (
                    <>
                        <SearchResults results={searchResults}/>
                        {searchSymbol.type === "crypto" && (
                            <p className="search-powered-by">
                                Powered by{" "}
                                <a href="https://www.coingecko.com/" target="_blank" rel="noopener noreferrer">
                                    CoinGecko
                                </a>
                            </p>
                        )}
                    </>
                ) : (
                    <div className="state-message">
                        <strong>No results for “{lastQuery}”</strong>
                        Check the spelling, or try switching between Stock and Crypto.
                    </div>
                )
            )}
        </div>
    )
}

export default SearchPage
