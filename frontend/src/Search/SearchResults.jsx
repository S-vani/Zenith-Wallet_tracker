import { useState } from "react";
import { useUser } from "../context/UserContext.jsx";
import { formatPercent, formatPrice } from "../utils/format.js";
import HoldingsChart from "../Holdings/HoldingsChart.jsx";
import AnalystPanel from "../Analyst/AnalystPanel.jsx";

import "../css/Holdings.css";

function SearchResults({ results }) {
    const [expandedId, setExpandedId] = useState(null);
    const { currency } = useUser();

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
                                {result.image && <img className="search-result-image" src={result.image} alt=""/>}
                                <div className="search-result-info">
                                    <span className="search-result-symbol">{result.symbol}</span>
                                    <span className="search-result-type">{result.type}</span>
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
                                <HoldingsChart symbol={result.api_id} type={result.type} initialRange="1D" compact/>
                                {/* research report for this asset; loads on its own so the chart isn't held up */}
                                <AnalystPanel key={`${result.type}-${result.api_id}`} symbol={result.api_id}
                                              type={result.type} coinId={result.coin_id} label={result.symbol}/>
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

export default SearchResults;
