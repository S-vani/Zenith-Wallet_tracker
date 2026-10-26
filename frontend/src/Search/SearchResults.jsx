import { useState } from "react";
import { useUser } from "../context/UserContext.jsx";
import { formatPercent, formatPrice, listingName } from "../utils/format.js";
import HoldingsChart from "../Holdings/HoldingsChart.jsx";
import AnalystPanel from "../Analyst/AnalystPanel.jsx";
import {isNative} from "../native/platform.js";
import {shareText} from "../native/share.js";

import "../css/Holdings.css";

function SearchResults({ results }) {
    const [expandedId, setExpandedId] = useState(null);
    const [brokenImages, setBrokenImages] = useState(() => new Set()); // logos that failed to load are left out
    const { currency } = useUser();

    const hideImage = (id) => setBrokenImages((current) => new Set(current).add(id));

    return (
        <div className="search-results-list">
            {results.map((result) => {
                const isExpanded = expandedId === result.api_id;
                const isPositive = result.change_pct >= 0;

                return (
                    <div key={result.api_id} className="search-result-wrapper">
                        <button className={`search-result-item${isExpanded ? " open" : ""}`}
                                onClick={() => setExpandedId(isExpanded ? null : result.api_id)}
                                aria-expanded={isExpanded}>
                            <div className="search-result-left">
                                {/* no logo (or a broken one) means no image at all, rather than an empty circle */}
                                {result.image && !brokenImages.has(result.api_id) && (
                                    <img className="search-result-image" src={result.image} alt=""
                                         onError={() => hideImage(result.api_id)}/>
                                )}
                                <div className="search-result-info">
                                    <span className="search-result-symbol">{result.symbol}</span>
                                    {listingName(result) ? (
                                        <span className="search-result-name" title={listingName(result)}>
                                            {listingName(result)}
                                        </span>
                                    ) : (
                                        <span className="search-result-type">{result.type}</span>
                                    )}
                                </div>
                            </div>

                            <div className="search-result-right">
                                <span className="search-result-price">
                                    {formatPrice(result.price, currency)}
                                </span>
                                <span className={`search-result-change ${isPositive ? "positive" : "negative"}`}>
                                    {formatPercent(result.change_pct)} today
                                </span>
                            </div>
                        </button>

                        {isExpanded && (
                            <div className="search-result-chart-box">
                                {/* same chart as holdings: axes, range buttons and tooltips */}
                                <HoldingsChart symbol={result.api_id} type={result.type} coinId={result.coin_id}
                                               initialRange="1D" compact/>
                                {/* research report for this asset; loads on its own so the chart isn't held up */}
                                <AnalystPanel key={`${result.type}-${result.api_id}`} symbol={result.api_id}
                                              type={result.type} coinId={result.coin_id} label={result.symbol}/>
                                {isNative && (
                                    <button type="button" className="btn search-share-btn"
                                            onClick={() => shareText({
                                                title: `${result.symbol.toUpperCase()} on Zenith`,
                                                text: `${result.symbol.toUpperCase()} is ${formatPrice(result.price, currency)} `
                                                    + `(${formatPercent(result.change_pct)} today).`,
                                                url: "https://zenithwalletracker.ca",
                                            })}>
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                                             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                            <path d="M12 3v12"/>
                                            <polyline points="8 7 12 3 16 7"/>
                                            <path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>
                                        </svg>
                                        Share {result.symbol.toUpperCase()}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

export default SearchResults;
