import {formatPrice} from "../utils/format.js";
import {formatShortPercent, orderScenarios, percentFrom, scenarioRanges} from "./analystUtils.js";
import AnalystDisclosure from "./AnalystDisclosure.jsx";
import useMediaQuery from "./useMediaQuery.js";
import {useState} from "react";

// Bull / base / bear cards with the 7- and 30-day price ranges in the report's currency
function AnalystScenarios({report, headingId}) {
    const scenarios = orderScenarios(report.scenarios);
    const isPhone = useMediaQuery("(max-width: 640px)");
    const [openConditions, setOpenConditions] = useState({}); // phones: which cards show their conditions
    if (scenarios.length === 0) return null;

    const {currency, price} = report.asset;
    const hasRanges = scenarios.some((s) => scenarioRanges(s).length > 0);

    return (
        <section className="analyst-section" aria-labelledby={headingId}>
            <div className="analyst-section-head">
                <h3 id={headingId} className="analyst-section-title">Scenarios</h3>
                {hasRanges && Number(price) > 0 && (
                    // the analysis works on daily candles, so this can differ a little from the live price above
                    <span className="analyst-section-note"
                          title="Ranges start from the last daily closing price, which can differ slightly from the live price.">
                        From last daily close, {formatPrice(price, currency)}
                    </span>
                )}
            </div>

            <div className="analyst-scenarios">
                {scenarios.map((scenario) => {
                    const ranges = scenarioRanges(scenario);
                    const conditions = (scenario.conditions ?? []).filter(Boolean);

                    return (
                        <article key={scenario.case} className={`analyst-card analyst-scenario ${scenario.case}`}>
                            <h4 className="analyst-scenario-title">
                                <span className="analyst-scenario-dot" aria-hidden="true"/>
                                {scenario.label}
                            </h4>
                            <p className="analyst-scenario-summary">{scenario.summary}</p>

                            {ranges.length > 0 && (
                                <dl className="analyst-ranges">
                                    {ranges.map((range) => (
                                        <div key={range.days} className="analyst-range">
                                            <dt>{range.days} days</dt>
                                            <dd>
                                                <span className="analyst-range-value">
                                                    <span className="analyst-range-price">{formatPrice(range.low, currency)}</span>
                                                    <span className="analyst-range-sep"> – </span>
                                                    <span className="analyst-range-price">{formatPrice(range.high, currency)}</span>
                                                </span>
                                                {Number(price) > 0 && (
                                                    <span className="analyst-range-pct">
                                                        {formatShortPercent(percentFrom(range.low, price))}
                                                        {" to "}
                                                        {formatShortPercent(percentFrom(range.high, price))}
                                                    </span>
                                                )}
                                            </dd>
                                        </div>
                                    ))}
                                </dl>
                            )}

                            {conditions.length > 0 && isPhone && (
                                <button type="button" className="analyst-conditions-toggle"
                                        aria-expanded={Boolean(openConditions[scenario.case])}
                                        onClick={() => setOpenConditions((open) => ({
                                            ...open, [scenario.case]: !open[scenario.case],
                                        }))}>
                                    What would need to happen
                                    <span className="analyst-disclosure-chevron" aria-hidden="true">▾</span>
                                </button>
                            )}
                            {conditions.length > 0 && (!isPhone || openConditions[scenario.case]) && (
                                <div className="analyst-conditions">
                                    {!isPhone && <h5 className="analyst-conditions-title">What would need to happen</h5>}
                                    <ul>
                                        {conditions.map((condition, i) => <li key={i}>{condition}</li>)}
                                    </ul>
                                </div>
                            )}
                        </article>
                    );
                })}
            </div>

            {hasRanges && report.range_method && (
                <AnalystDisclosure title="How these ranges are calculated" className="analyst-disclosure-small">
                    <p className="analyst-muted-text">{report.range_method}</p>
                </AnalystDisclosure>
            )}
            {!hasRanges && (
                <p className="analyst-muted-text">
                    Price ranges aren't available for this asset, so these scenarios are qualitative only.
                </p>
            )}
        </section>
    );
}

export default AnalystScenarios;
