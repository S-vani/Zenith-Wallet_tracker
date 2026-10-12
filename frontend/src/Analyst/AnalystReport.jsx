import {useId} from "react";
import {formatEventDate, humanize, toneClass} from "./analystUtils.js";
import AnalystOverview from "./AnalystOverview.jsx";
import AnalystScenarios from "./AnalystScenarios.jsx";
import {AnalystMetrics, AnalystSources} from "./AnalystDetails.jsx";

// Body of a finished report (status "ok"): overview, insights, scenarios, watch list, risk, bottom line, details
function AnalystReport({report, now}) {
    const ids = useId();
    const insights = (report.insights ?? []).filter((i) => i?.title);
    const watch = (report.watch ?? []).filter((w) => w?.title).slice(0, 3);

    return (
        <>
            <AnalystOverview report={report}/>

            {insights.length > 0 && (
                <section className="analyst-section" aria-labelledby={`${ids}-insights`}>
                    <h3 id={`${ids}-insights`} className="analyst-section-title">Key insights</h3>
                    <div className="analyst-insights">
                        {insights.map((insight, i) => (
                            <article key={i} className={`analyst-card analyst-insight tone-${toneClass(insight.tone)}`}>
                                {insight.kind && <span className="analyst-kind">{humanize(insight.kind)}</span>}
                                <h4 className="analyst-insight-title">{insight.title}</h4>
                                <p className="analyst-insight-detail">{insight.detail}</p>
                            </article>
                        ))}
                    </div>
                </section>
            )}

            <AnalystScenarios report={report} headingId={`${ids}-scenarios`}/>

            {(watch.length > 0 || report.main_risk) && (
                <div className={`analyst-split${watch.length > 0 && report.main_risk ? "" : " single"}`}>
                    {watch.length > 0 && (
                        <section className="analyst-section" aria-labelledby={`${ids}-watch`}>
                            <h3 id={`${ids}-watch`} className="analyst-section-title">What to watch</h3>
                            <ul className="analyst-watch">
                                {watch.map((item, i) => {
                                    const date = formatEventDate(item.date, now);
                                    return (
                                        <li key={i} className="analyst-watch-item">
                                            <div className="analyst-watch-head">
                                                <span className="analyst-watch-title">{item.title}</span>
                                                {date ? (
                                                    <span className="analyst-watch-date">
                                                        <time dateTime={item.date}>{date.label}</time>
                                                        <span className="analyst-watch-relative"> · {date.relative}</span>
                                                    </span>
                                                ) : item.kind && (
                                                    <span className="analyst-kind">{humanize(item.kind)}</span>
                                                )}
                                            </div>
                                            <p className="analyst-watch-detail">{item.detail}</p>
                                        </li>
                                    );
                                })}
                            </ul>
                        </section>
                    )}

                    {report.main_risk && (
                        <section className="analyst-risk" aria-labelledby={`${ids}-risk`}>
                            <h3 id={`${ids}-risk`} className="analyst-section-title">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                                     strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>
                                    <line x1="12" y1="9" x2="12" y2="13"/>
                                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                                </svg>
                                Main risk
                            </h3>
                            <p className="analyst-risk-title">{report.main_risk.title}</p>
                            <p className="analyst-risk-detail">{report.main_risk.detail}</p>
                        </section>
                    )}
                </div>
            )}

            {report.bottom_line && (
                <section className="analyst-bottom-line" aria-labelledby={`${ids}-bottom`}>
                    <h3 id={`${ids}-bottom`} className="analyst-section-title">Bottom line</h3>
                    <p>{report.bottom_line}</p>
                </section>
            )}

            <div className="analyst-details">
                <AnalystMetrics metrics={report.metrics}/>
                <AnalystSources sources={report.sources} limitations={report.limitations}/>
            </div>
        </>
    );
}

export default AnalystReport;
