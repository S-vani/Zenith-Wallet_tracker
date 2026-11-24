import {useState} from "react";
import AssetAvatar from "../components/AssetAvatar.jsx";
import {useUser} from "../context/UserContext.jsx";
import {formatPercent, formatPrice, listingName} from "../utils/format.js";
import HoldingsChart from "../Holdings/HoldingsChart.jsx";
import AnalystPanel from "../Analyst/AnalystPanel.jsx";
import {isNative} from "../native/platform.js";
import {shareText} from "../native/share.js";
import AlertForm from "../Alerts/AlertForm.jsx";

import "../css/Holdings.css";

// One search result opened: a header with the price and today's change, ☆ watch and 🔔 alert buttons, the price
// chart and the Market Analyst report. On phones it replaces the results (with a "Results" back button); on wide
// screens it sits beside them. `watched` / `onToggleWatch` come from the page, which keeps the watchlist.
function AssetDetail({result, onBack, watched = false, onToggleWatch}) {
    const {currency} = useUser();
    const [logoFailed, setLogoFailed] = useState(false);
    const [alerting, setAlerting] = useState(false);
    const change = Number(result.change_pct);
    const symbol = result.symbol.toUpperCase();

    return (
        <article className="asset-detail" aria-labelledby="asset-detail-title">
            <button type="button" className="asset-detail-back" onClick={onBack}>
                <svg viewBox="0 0 12 20" aria-hidden="true">
                    <path d="M10 2 2 10l8 8" fill="none" stroke="currentColor" strokeWidth="2.6"
                          strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                Results
            </button>

            <header className="asset-detail-head">
                {result.image && !logoFailed ? (
                    <img className="asset-detail-logo" src={result.image} alt="" onError={() => setLogoFailed(true)}/>
                ) : (
                    <AssetAvatar symbol={result.symbol} type={result.type}/>
                )}
                <div className="asset-detail-names">
                    <h2 id="asset-detail-title">{symbol}</h2>
                    <span>{listingName(result) || (result.type === "crypto" ? "Crypto" : "Stock")}</span>
                </div>
                <button type="button" className={`asset-detail-icon${watched ? " on" : ""}`}
                        aria-pressed={watched} aria-label={watched ? `Remove ${symbol} from watchlist`
                            : `Add ${symbol} to watchlist`} onClick={onToggleWatch}>
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"
                              fill={watched ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8"
                              strokeLinejoin="round"/>
                    </svg>
                </button>
                <button type="button" className={`asset-detail-icon${alerting ? " on" : ""}`}
                        aria-expanded={alerting} aria-label={`Set a price alert for ${symbol}`}
                        onClick={() => setAlerting(!alerting)}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
                         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M18 16v-5a6 6 0 0 0-12 0v5l-2 2h16z"/>
                        <path d="M10 20a2 2 0 0 0 4 0"/>
                    </svg>
                </button>
                {isNative && (
                    <button type="button" className="asset-detail-icon" aria-label={`Share ${symbol}`}
                            onClick={() => shareText({
                                title: `${symbol} on Zenith`,
                                text: `${symbol} is ${formatPrice(result.price, currency)} (${formatPercent(change)} today).`,
                                url: "https://zenithwalletracker.ca",
                            })}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M12 3v12"/>
                            <polyline points="8 7 12 3 16 7"/>
                            <path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/>
                        </svg>
                    </button>
                )}
            </header>

            <div className="asset-detail-price">
                <span className="asset-detail-amount">{formatPrice(result.price, currency)}</span>
                {Number.isFinite(change) && (
                    <span className={`change-pill ${change >= 0 ? "positive" : "negative"}`}>
                        {formatPercent(change)} today
                    </span>
                )}
            </div>

            {alerting && <AlertForm asset={result} onDone={() => setAlerting(false)}/>}

            {/* same chart as holdings: axes, range buttons and tooltips */}
            <div className="asset-detail-chart">
                <HoldingsChart symbol={result.api_id} type={result.type} coinId={result.coin_id} initialRange="1D"
                               compact/>
            </div>

            {/* the research report loads on its own, so the chart isn't held up */}
            <AnalystPanel key={`${result.type}-${result.api_id}`} symbol={result.api_id} type={result.type}
                          coinId={result.coin_id} label={result.symbol}/>
        </article>
    );
}

export default AssetDetail;
