import {useId} from "react";
import useAnalystReport from "./useAnalystReport.js";
import useNow from "./useNow.js";
import {
    engineMeta,
    formatCountdown,
    formatPeriod,
    formatRelativeTime,
    formatTimestamp,
    parseDate,
} from "./analystUtils.js";
import AnalystReport from "./AnalystReport.jsx";
import AnalystSkeleton from "./AnalystSkeleton.jsx";
import {AnalystSources} from "./AnalystDetails.jsx";

import "../css/Analyst.css";

// Research panel shown under the chart of the selected search result. Loads on its own, so the chart
// keeps working while the report is generated.
function AnalystPanel({symbol, type, coinId, label}) {
    const titleId = useId();
    const {loading, report, error, refreshing, refreshError, retry, refresh} = useAnalystReport({symbol, type, coinId});

    const refreshAt = parseDate(report?.refresh_available_at)?.getTime() ?? null;
    const now = useNow(15000, refreshAt);

    const ticker = String(label || symbol).toUpperCase();
    const assetName = report?.asset?.name || ticker;

    let body;
    if (loading) {
        body = (
            <>
                <p className="sr-only" role="status">Loading the market analysis for {ticker}…</p>
                <AnalystSkeleton/>
            </>
        );
    } else if (error) {
        body = (
            <div className="alert-error analyst-error" role="alert">
                <span>{error}</span>
                <button type="button" className="btn" onClick={retry}>Retry</button>
            </div>
        );
    } else if (report.status === "insufficient_data") {
        body = (
            <>
                <div className="analyst-card analyst-empty">
                    <h3 className="analyst-empty-title">Not enough data for a full analysis</h3>
                    <p>{report.summary}</p>
                    {(report.limitations ?? []).length > 0 && (
                        <ul className="analyst-limitations">
                            {report.limitations.filter(Boolean).map((note, i) => <li key={i}>{note}</li>)}
                        </ul>
                    )}
                </div>
                <div className="analyst-details">
                    <AnalystSources sources={report.sources}/>
                </div>
            </>
        );
    } else {
        body = <AnalystReport report={report} now={now}/>;
    }

    return (
        <section className="analyst" aria-labelledby={titleId} aria-busy={loading || refreshing}>
            <header className="analyst-header">
                <div className="analyst-heading">
                    <div className="analyst-title-row">
                        <svg className="analyst-logo" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M3 3v18h18"/>
                            <polyline points="7 14 11 10 14 13 20 7"/>
                        </svg>
                        <h2 id={titleId} className="analyst-title">Market Analyst</h2>
                        {report && <EngineBadge engine={report.engine}/>}
                    </div>
                    <p className="analyst-meta">
                        <span className="analyst-meta-item analyst-asset">{assetName}</span>
                        {report?.generated_at && (
                            <span className="analyst-meta-item">
                                Updated{" "}
                                <time dateTime={report.generated_at} title={formatTimestamp(report.generated_at)}>
                                    {formatRelativeTime(report.generated_at, now)}
                                </time>
                            </span>
                        )}
                        {report?.period && (
                            <span className="analyst-meta-item">Data: {formatPeriod(report.period)}</span>
                        )}
                    </p>
                </div>

                {report && (
                    <RefreshButton refreshing={refreshing} countdown={formatCountdown(refreshAt, now)}
                                   onRefresh={refresh}/>
                )}
            </header>

            {refreshError && (
                <p className={refreshError.status === 429 ? "analyst-notice" : "alert-error"} role="status">
                    {refreshError.message}
                </p>
            )}

            {report?.stale && (
                <p className="analyst-notice" role="note">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <circle cx="12" cy="12" r="9"/>
                        <polyline points="12 7 12 12 15 14"/>
                    </svg>
                    <span>
                        <strong>Data may be out of date.</strong>
                        {report.stale_reason && ` ${report.stale_reason}`}
                    </span>
                </p>
            )}

            {body}

            {report?.disclaimer && <p className="analyst-disclaimer">{report.disclaimer}</p>}
        </section>
    );
}

function EngineBadge({engine}) {
    const meta = engineMeta(engine);
    return (
        <span className={`analyst-engine ${engine === "gemini" ? "ai" : "rules"}`} title={meta.description}>
            {meta.label}
        </span>
    );
}

function RefreshButton({refreshing, countdown, onRefresh}) {
    const coolingDown = Boolean(countdown) && !refreshing;
    let text = "Refresh";
    if (refreshing) text = "Refreshing…";
    else if (coolingDown) text = `Refresh in ${countdown}`;

    return (
        <button type="button" className="btn analyst-refresh" onClick={onRefresh} disabled={refreshing || coolingDown}
                title={coolingDown ? `A new analysis can be requested in ${countdown}` : "Generate a fresh analysis"}>
            {refreshing ? (
                <span className="spinner analyst-refresh-spinner" aria-hidden="true"/>
            ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                     strokeLinejoin="round" aria-hidden="true">
                    <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                    <polyline points="21 3 21 9 15 9"/>
                </svg>
            )}
            {text}
        </button>
    );
}

export default AnalystPanel;
