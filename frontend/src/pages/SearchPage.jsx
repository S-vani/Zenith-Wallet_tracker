import "../css/Search.css"
import {useEffect, useRef, useState} from "react";
import {useLocation, useNavigate, useSearchParams} from "react-router-dom";
import {searchCrypto, searchStock} from "../services/api.js";
import SearchResults from "../Search/SearchResults.jsx"
import AssetDetail from "../Search/AssetDetail.jsx";
import {loadRecent, rememberRecent} from "../Search/recentSearches.js";
import usePageTitle from "../utils/usePageTitle.js";
import {isNative} from "../native/platform.js";

// tappable picks shown before the first search
const POPULAR = {
    stock: ["AAPL", "NVDA", "MSFT", "TSLA", "VOO", "SHOP.TO"],
    crypto: ["BTC", "ETH", "SOL", "XRP", "DOGE", "USDT"],
};

const MAX_QUERY_LENGTH = 20; // the backend rejects longer searches

// Stock and crypto search. The results are one list; picking one opens its detail (price, chart, Market Analyst),
// which replaces the list on phones and sits beside it on wide screens. The open asset is in the address
// (?asset=…), so Back closes it like any other screen.
function SearchPage() {
    usePageTitle("Search");
    const navigate = useNavigate();
    const location = useLocation();
    const [params, setParams] = useSearchParams();

    const [searchSymbol, setSearchSymbol] = useState({"symbol": "", "type": "stock"});
    const [searchResults, setSearchResults] = useState(null) // null until the first search
    const [lastQuery, setLastQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [recent, setRecent] = useState(loadRecent);
    const searchId = useRef(0); // only the newest search may update the page

    const selectedId = params.get("asset");
    const selected = selectedId ? searchResults?.find((r) => r.api_id === selectedId) ?? null : null;

    // a new asset opens at the top of its detail (on phones the list was scrolled somewhere else)
    useEffect(() => {
        if (selected) window.scrollTo(0, 0);
    }, [selected]);

    function setType(type) {
        searchId.current += 1;
        setLoading(false);
        // tickers rarely mean the same thing in both lists (AAPL isn't a coin), so start over instead of
        // re-searching the old text, which also spent a rate-limited provider call on a likely error
        setSearchSymbol({symbol: "", type});
        setSearchResults(null);
        setError(null);
        if (selectedId) setParams({}, {replace: true});
    }

    function searchBarSubmit(e) {
        e.preventDefault();
        const query = searchSymbol.symbol.trim();
        if (!query) return;
        e.target.querySelector("input")?.blur(); // the keyboard goes away so the results can be seen
        runSearch(query, searchSymbol.type);
    }

    function searchFor(symbol) {
        setSearchSymbol({...searchSymbol, symbol});
        runSearch(symbol, searchSymbol.type);
    }

    function clearSearch() {
        searchId.current += 1;
        setLoading(false);
        setSearchSymbol({...searchSymbol, symbol: ""});
        setSearchResults(null);
        setError(null);
        if (selectedId) setParams({}, {replace: true});
    }

    async function runSearch(query, type) {
        const id = ++searchId.current;
        setLoading(true);
        setError(null);
        if (selectedId) setParams({}, {replace: true});
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

    const open = (result) => {
        setRecent(rememberRecent(result.symbol, result.type));
        // pushed, so the phone's back gesture / the browser's Back closes the detail
        setParams({asset: result.api_id}, {replace: Boolean(selectedId), state: {openedFromList: true}});
    };

    const close = () => {
        if (location.state?.openedFromList) navigate(-1);
        else setParams({}, {replace: true});
    };

    const credit = searchSymbol.type === "crypto" ? (
        // CoinGecko's free plan asks for this credit next to its data
        <span className="search-powered-by">
            Powered by{" "}
            <a href="https://www.coingecko.com/" target="_blank" rel="noopener noreferrer">CoinGecko</a>
        </span>
    ) : null;

    const recentOfType = recent.filter((r) => r.type === searchSymbol.type);

    return (
        <div className={`app-page search-page-wrapper${selected ? " has-detail" : ""}`}>
            <header className="search-header">
                <h1 className="page-headers">Search</h1>
                <p className="page-subtitle">Prices, charts and a Market Analyst report for US and Canadian stocks,
                    ETFs and crypto.</p>
            </header>

            <div className="search-area">
                <form className="search-form" role="search" onSubmit={searchBarSubmit}>
                    <div className="search-field">
                        <svg className="search-form-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                             strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                            <circle cx="11" cy="11" r="7"/>
                            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                        </svg>
                        <input
                            value={searchSymbol.symbol}
                            onChange={(e) => setSearchSymbol({...searchSymbol, symbol: e.target.value})}
                            className="search-bar"
                            type="text"
                            aria-label={`Search ${searchSymbol.type === "stock" ? "stocks and ETFs" : "crypto"}`}
                            placeholder={searchSymbol.type === "stock" ? "Ticker or company, e.g. AAPL" : "Coin, e.g. BTC"}
                            autoComplete="off"
                            autoCapitalize="characters"
                            spellCheck={false}
                            maxLength={MAX_QUERY_LENGTH}
                            enterKeyHint="search"
                            autoFocus={!isNative} /* the app opens the tab without throwing up the keyboard */
                        />
                        {loading && <span className="search-spinner" aria-hidden="true"/>}
                        {!loading && searchSymbol.symbol && (
                            <button type="button" className="search-clear" onClick={clearSearch}
                                    aria-label="Clear search">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M8 8l8 8M16 8l-8 8" fill="none" stroke="currentColor" strokeWidth="2.4"
                                          strokeLinecap="round"/>
                                </svg>
                            </button>
                        )}
                    </div>
                    <button className="btn btn-primary search-submit" type="submit"
                            disabled={loading || !searchSymbol.symbol.trim()}>
                        Search
                    </button>
                </form>

                <div className="segmented search-scope" role="group" aria-label="Asset type">
                    {[["stock", "Stocks & ETFs"], ["crypto", "Crypto"]].map(([type, label]) => (
                        <button key={type} type="button" className={searchSymbol.type === type ? "active" : ""}
                                aria-pressed={searchSymbol.type === type} onClick={() => setType(type)}>
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            {loading && <p className="visually-hidden" role="status">Searching…</p>}
            {error && <p className="alert-error search-error" role="alert">{error}</p>}

            {!searchResults && !loading && !error && (
                <div className="search-intro">
                    {recentOfType.length > 0 && (
                        <SuggestionGroup title="Recent" symbols={recentOfType.map((r) => r.symbol)}
                                         onPick={searchFor}/>
                    )}
                    <SuggestionGroup title="Popular" symbols={POPULAR[searchSymbol.type]} onPick={searchFor}/>
                    <p className="search-intro-note">
                        Pick a result to see its price chart and an automated Market Analyst report.
                    </p>
                </div>
            )}

            {searchResults && (
                searchResults.length > 0 ? (
                    <div className="search-layout">
                        <SearchResults results={searchResults} selectedId={selected?.api_id ?? null} onSelect={open}
                                       credit={credit}/>
                        {selected && <AssetDetail key={selected.api_id} result={selected} onBack={close}/>}
                    </div>
                ) : (
                    <div className="state-message">
                        <strong>No results for “{lastQuery}”</strong>
                        Check the spelling, or try {searchSymbol.type === "stock" ? "Crypto" : "Stocks & ETFs"}.
                    </div>
                )
            )}
        </div>
    )
}

// A row of tappable symbols under a small heading ("Recent", "Popular")
function SuggestionGroup({title, symbols, onPick}) {
    return (
        <section className="search-suggestions" aria-label={title}>
            <h2>{title}</h2>
            <div className="search-examples">
                {symbols.map((symbol) => (
                    <button key={symbol} type="button" className="search-example" onClick={() => onPick(symbol)}>
                        {symbol}
                    </button>
                ))}
            </div>
        </section>
    );
}

export default SearchPage
