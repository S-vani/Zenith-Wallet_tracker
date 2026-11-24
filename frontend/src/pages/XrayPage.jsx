import {useEffect, useState} from "react";
import {getPortfolioXray} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {formatMoney, formatSignedMoney} from "../utils/format.js";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";
import ScoreRing from "../Xray/ScoreRing.jsx";

import "../css/Xray.css";

const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;
const signedPct = (x, digits = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(digits)}%`;
const LEVEL_ICONS = {warn: "!", info: "i", good: "✓"};
const EXPOSURE_TABS = [["sectors", "Sectors"], ["regions", "Regions"], ["companies", "Companies"]];

// Portfolio X-Ray: the rules-based analyst for the whole portfolio (backend/services/xray.py). A score, plain-English
// findings, what you really own once ETFs are opened up, how the portfolio moves against the market, and what a few
// stress scenarios would cost. Everything is computed from today's holdings and a year of prices; nothing is advice.
function XrayPage() {
    usePageTitle("Portfolio X-Ray");
    const {currency} = useUser();
    const refreshKey = useRefreshKey();
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [tab, setTab] = useState("sectors");

    useEffect(() => {
        if (!currency) return undefined;
        let ignore = false;
        getPortfolioXray()
            .then((d) => !ignore && (setData(d), setError(null)))
            .catch((err) => !ignore && setError(err.message));
        return () => {
            ignore = true;
        };
    }, [currency, refreshKey]);

    if (error) {
        return (
            <div className="app-page xray-page">
                <h1 className="page-headers">Portfolio X-Ray</h1>
                <p className="alert-error" role="alert">{error}</p>
            </div>
        );
    }
    if (!data) {
        return (
            <div className="state-message" role="status">
                <div className="spinner"/>Reading a year of prices for your holdings…
            </div>
        );
    }
    if (data.empty) {
        return (
            <div className="app-page xray-page">
                <h1 className="page-headers">Portfolio X-Ray</h1>
                <div className="state-message">
                    <strong>Nothing to X-ray yet</strong>
                    Add a few trades and the X-Ray shows how concentrated and risky your portfolio is.
                </div>
            </div>
        );
    }

    const {score, risk, exposure, stress_tests: tests, findings, concentration} = data;
    const rows = exposure[tab] ?? [];
    const biggest = Math.max(...rows.map((r) => r.weight), 0.0001);

    return (
        <div className="app-page xray-page">
            <header>
                <h1 className="page-headers">Portfolio X-Ray</h1>
                <p className="page-subtitle">How spread out and how risky your portfolio really is.</p>
            </header>

            <section className="xray-hero">
                <ScoreRing score={score.score}/>
                <div className="xray-hero-text">
                    <span className="xray-score-label">{score.label}</span>
                    <span className="xray-hero-sub">
                        Diversification score for {formatMoney(data.total, currency)} across{" "}
                        {concentration.count} {concentration.count === 1 ? "holding" : "holdings"}
                    </span>
                    <span className="xray-hero-sub">
                        Spread like {concentration.effective_holdings.toFixed(1)} equal holdings · top holding{" "}
                        {pct(concentration.top?.weight ?? 0)}
                    </span>
                </div>
            </section>

            {findings.length > 0 && (
                <section className="xray-section" aria-labelledby="xray-findings">
                    <h2 id="xray-findings">What stands out</h2>
                    <ul className="xray-findings">
                        {findings.map((f) => (
                            <li key={f.title} className={`xray-finding ${f.level}`}>
                                <span className="xray-finding-icon" aria-hidden="true">{LEVEL_ICONS[f.level]}</span>
                                <span>
                                    <strong>{f.title}</strong>
                                    <span>{f.text}</span>
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <section className="xray-section" aria-labelledby="xray-own">
                <h2 id="xray-own">What you really own</h2>
                <div className="segmented xray-tabs" role="group" aria-label="Show exposure by">
                    {EXPOSURE_TABS.map(([value, label]) => (
                        <button key={value} type="button" className={tab === value ? "active" : ""}
                                aria-pressed={tab === value} onClick={() => setTab(value)}>{label}</button>
                    ))}
                </div>
                <ul className="xray-bars">
                    {rows.slice(0, 8).map((r) => (
                        <li key={r.name}>
                            <span className="xray-bar-name">
                                {r.name}
                                {r.via?.length > 0 && <small> incl. via {r.via.join(", ")}</small>}
                            </span>
                            <span className="xray-bar-track" aria-hidden="true">
                                <span className="xray-bar-fill" style={{width: `${(r.weight / biggest) * 100}%`}}/>
                            </span>
                            <span className="xray-bar-value">{pct(r.weight, 1)}</span>
                        </li>
                    ))}
                </ul>
                {tab === "companies" && (
                    <p className="xray-note">Your direct holdings plus each ETF's largest holdings, weighted by how
                        much of the fund you own.</p>
                )}
            </section>

            <section className="xray-section" aria-labelledby="xray-risk">
                <h2 id="xray-risk">How it moves</h2>
                {risk.volatility === undefined ? (
                    <p className="xray-note">
                        There isn't a long enough shared price history yet ({risk.days ?? 0} trading days) to measure
                        risk.
                    </p>
                ) : (
                    <>
                        <div className="xray-tiles">
                            <Tile label="Yearly swings" value={pct(risk.volatility)}
                                  hint="volatility: how much it typically moves in a year"/>
                            <Tile label="Worst drop" value={pct(-risk.max_drawdown)}
                                  hint="from a high, over the past year"/>
                            {risk.beta !== undefined && (
                                <Tile label={`vs ${data.benchmark}`} value={`${risk.beta.toFixed(2)}×`}
                                      hint="beta: 1× moves like the index"/>
                            )}
                            <Tile label="Past year" value={signedPct(risk.one_year_return)}
                                  hint="today's holdings, held all year"/>
                        </div>
                        {risk.correlated_pairs?.length > 0 && (
                            <p className="xray-note">
                                Move together: {risk.correlated_pairs.map((p) => `${p.a} & ${p.b}`).join(", ")}.
                            </p>
                        )}
                    </>
                )}
            </section>

            {tests.length > 0 && (
                <section className="xray-section" aria-labelledby="xray-tests">
                    <h2 id="xray-tests">What if…</h2>
                    <ul className="xray-tests">
                        {tests.map((t) => (
                            <li key={t.name}>
                                <span className="xray-test-text">
                                    <strong>{t.name}</strong>
                                    <span>{t.how}</span>
                                </span>
                                <span className={`xray-test-change ${t.change < 0 ? "negative" : "positive"}`}>
                                    {formatSignedMoney(t.change, currency)}
                                    <small>{signedPct(t.change_pct)}</small>
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <section className="xray-section xray-footer">
                {data.unpriced.length > 0 && (
                    <p>Left out (no price right now): {data.unpriced.join(", ")}.</p>
                )}
                {data.limitations.map((l) => <p key={l}>{l}</p>)}
                <p><strong>Not financial advice.</strong> Generated automatically from market data, for information
                    only.</p>
            </section>
        </div>
    );
}

function Tile({label, value, hint}) {
    return (
        <div className="xray-tile">
            <span className="xray-tile-label">{label}</span>
            <span className="xray-tile-value">{value}</span>
            <span className="xray-tile-hint">{hint}</span>
        </div>
    );
}

export default XrayPage;
