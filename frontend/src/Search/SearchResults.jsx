import {useState} from "react";
import AssetAvatar from "../components/AssetAvatar.jsx";
import {useUser} from "../context/UserContext.jsx";
import {formatPercent, formatPrice, listingName} from "../utils/format.js";

// The search results as one list (like the holdings list): logo or badge, symbol and name, price and today's change.
// Picking one opens its detail (AssetDetail.jsx) instead of unfolding a whole report inside the list.
function SearchResults({results, selectedId, onSelect, credit = null}) {
    const [brokenImages, setBrokenImages] = useState(() => new Set()); // logos that failed to load are left out
    const {currency} = useUser();

    return (
        <section className="search-results" aria-label="Search results">
            <div className="search-results-head">
                <span>{results.length} {results.length === 1 ? "result" : "results"}</span>
                {credit}
            </div>
            <ul className="search-results-list">
                {results.map((result) => {
                    const selected = selectedId === result.api_id;
                    const change = Number(result.change_pct);
                    return (
                        <li key={result.api_id}>
                            <button type="button" className={`search-result-item${selected ? " selected" : ""}`}
                                    aria-current={selected || undefined} onClick={() => onSelect(result)}>
                                {/* the coin's own logo when CoinGecko has one, otherwise a lettered badge */}
                                {result.image && !brokenImages.has(result.api_id) ? (
                                    <img className="search-result-image" src={result.image} alt=""
                                         onError={() => setBrokenImages((s) => new Set(s).add(result.api_id))}/>
                                ) : (
                                    <AssetAvatar symbol={result.symbol} type={result.type}/>
                                )}
                                <span className="search-result-info">
                                    <span className="search-result-symbol">{result.symbol}</span>
                                    <span className="search-result-name" title={listingName(result) || undefined}>
                                        {listingName(result) || (result.type === "crypto" ? "Crypto" : "Stock")}
                                    </span>
                                </span>
                                <span className="search-result-right">
                                    <span className="search-result-price">{formatPrice(result.price, currency)}</span>
                                    {Number.isFinite(change) && (
                                        <span className={`change-pill ${change >= 0 ? "positive" : "negative"}`}>
                                            {formatPercent(change)}
                                        </span>
                                    )}
                                </span>
                                <span className="search-result-chevron" aria-hidden="true">›</span>
                            </button>
                        </li>
                    );
                })}
            </ul>
        </section>
    );
}

export default SearchResults;
