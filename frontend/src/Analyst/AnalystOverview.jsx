import {CONFIDENCE_MEANING, confidenceMeta, formatScore, scorePosition, sentimentMeta} from "./analystUtils.js";

// Sentiment badge, confidence, score gauge, the summary and the main reasons
function AnalystOverview({report}) {
    const sentiment = sentimentMeta(report.sentiment);
    const confidence = confidenceMeta(report.confidence);
    const position = scorePosition(report.score);
    const reasons = (report.reasons ?? []).filter(Boolean);

    return (
        <div className={`analyst-overview analyst-card${sentiment ? ` sentiment-${sentiment.className}` : ""}`}>
            {sentiment && (
                <div className="analyst-sentiment">
                    <span className="analyst-sentiment-label">Signal summary</span>
                    <span className={`analyst-sentiment-badge ${sentiment.className}`}>
                        <SentimentIcon sentiment={sentiment.className}/>
                        {sentiment.label}
                    </span>

                    {confidence && (
                        <span className="analyst-confidence" title={CONFIDENCE_MEANING}>
                            <span className="analyst-confidence-bars" aria-hidden="true">
                                {[1, 2, 3].map((n) => (
                                    <span key={n} className={n <= confidence.level ? "on" : ""}/>
                                ))}
                            </span>
                            {confidence.label}
                        </span>
                    )}

                    {position !== null && (
                        <div className="analyst-gauge">
                            <div className="analyst-gauge-track" role="img"
                                 aria-label={`Signal score ${formatScore(report.score)} on a scale from −1 (bearish) to +1 (bullish)`}>
                                <span className="analyst-gauge-value" aria-hidden="true"
                                      style={{left: `${Math.min(92, Math.max(8, position))}%`}}>
                                    {formatScore(report.score)}
                                </span>
                                <span className="analyst-gauge-marker" style={{left: `${position}%`}}/>
                            </div>
                            <div className="analyst-gauge-scale" aria-hidden="true">
                                <span>Bearish</span>
                                <span>Neutral</span>
                                <span>Bullish</span>
                            </div>
                        </div>
                    )}
                </div>
            )}

            <div className="analyst-overview-text">
                <p className="analyst-summary">{report.summary}</p>
                {reasons.length > 0 && (
                    <>
                        <h3 className="analyst-subheading">Why</h3>
                        <ul className="analyst-reasons">
                            {reasons.map((reason, i) => <li key={i}>{reason}</li>)}
                        </ul>
                    </>
                )}
            </div>
        </div>
    );
}

// The arrow beside the sentiment: up, down or flat.
function SentimentIcon({sentiment}) {
    const common = {
        viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2.4,
        strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, className: "analyst-sentiment-icon",
    };
    if (sentiment === "bullish") {
        return <svg {...common}><polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/></svg>;
    }
    if (sentiment === "bearish") {
        return <svg {...common}><polyline points="3 7 9 13 13 9 21 17"/><polyline points="15 17 21 17 21 11"/></svg>;
    }
    return <svg {...common}><line x1="4" y1="12" x2="20" y2="12"/><polyline points="15 7 20 12 15 17"/></svg>;
}

export default AnalystOverview;
