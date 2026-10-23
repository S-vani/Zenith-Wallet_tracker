import {formatDate, groupMetrics, safeUrl} from "./analystUtils.js";
import AnalystDisclosure from "./AnalystDisclosure.jsx";
import {isNative} from "../native/platform.js";

// The facts behind the wording, grouped (performance, trend, risk, ...)
export function AnalystMetrics({metrics}) {
    const groups = groupMetrics(metrics);
    if (groups.length === 0) return null;
    const count = groups.reduce((n, g) => n + g.items.length, 0);

    return (
        <AnalystDisclosure title="Data behind this analysis" hint={`${count} data points`}>
            <div className="analyst-metric-groups">
                {groups.map((group) => (
                    <div key={group.group} className="analyst-metric-group">
                        <h4 className="analyst-subheading">{group.label}</h4>
                        <dl className="analyst-metrics">
                            {group.items.map((metric, i) => (
                                <div key={`${metric.label}-${i}`} className="analyst-metric">
                                    <dt>{metric.label}</dt>
                                    <dd>{metric.value}</dd>
                                </div>
                            ))}
                        </dl>
                    </div>
                ))}
            </div>
        </AnalystDisclosure>
    );
}

// Where the data came from and what's missing
export function AnalystSources({sources = [], limitations = []}) {
    const items = sources.filter((s) => s?.name);
    const notes = limitations.filter(Boolean);
    if (items.length === 0 && notes.length === 0) return null;

    return (
        <AnalystDisclosure title="Sources & limitations">
            {items.length > 0 && (
                <>
                    <h4 className="analyst-subheading">Sources</h4>
                    <ul className="analyst-sources">
                        {items.map((source, i) => {
                            const url = safeUrl(source.url);
                            const asOf = formatDate(source.as_of);
                            return (
                                <li key={`${source.name}-${i}`}>
                                    {url ? (
                                        <a href={url} target="_blank" rel="noopener noreferrer"
                                           className="analyst-source-link">
                                            {source.name}
                                            {/* the app opens it in an in-app Safari sheet instead (externalLinks.js) */}
                                            {!isNative && <span className="sr-only"> (opens in a new tab)</span>}
                                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                                                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                                <path d="M14 4h6v6"/>
                                                <path d="M20 4l-9 9"/>
                                                <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>
                                            </svg>
                                        </a>
                                    ) : (
                                        <span className="analyst-source-name">{source.name}</span>
                                    )}
                                    {asOf && <span className="analyst-source-date">as of {asOf}</span>}
                                </li>
                            );
                        })}
                    </ul>
                </>
            )}

            {notes.length > 0 && (
                <>
                    <h4 className="analyst-subheading">Limitations</h4>
                    <ul className="analyst-limitations">
                        {notes.map((note, i) => <li key={i}>{note}</li>)}
                    </ul>
                </>
            )}
        </AnalystDisclosure>
    );
}
