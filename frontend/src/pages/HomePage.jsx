import {Link} from "react-router-dom";
import {getToken, getUserCount} from "../services/api.js";
import usePageTitle from "../utils/usePageTitle.js";
import DemoVideoModal from "../Home/DemoVideoModal.jsx";

import "../css/Home.css"
import {useCallback, useEffect, useRef, useState} from "react";

function HomePage() {
    usePageTitle(null);
    const [userCount, setUserCount] = useState(null);
    const loggedIn = Boolean(getToken());
    const [demoOpen, setDemoOpen] = useState(false);
    const demoButtonRef = useRef(null);
    const closeDemo = useCallback(() => setDemoOpen(false), []);

    useEffect(() => {
        getUserCount().then(setUserCount).catch(() => null);
    }, []);


    return (
        <>
        {/* inert: keyboard and screen readers can't reach the page behind the demo video */}
        <div className="home-page" inert={demoOpen}>
            <header className="home-topbar">
                <Link to="/" className="home-brand">
                    <img className="brand-mark" src="/zenith-logo.svg" alt="" width="32" height="32"/>
                    <span className="brand-name">Zenith&nbsp;<span className="brand-accent">Wallet Tracker</span></span>
                </Link>
                <nav className="home-auth" aria-label="Account">
                    {loggedIn ? (
                        <Link to="/dashboard" className="auth-btn signup-btn">Open dashboard</Link>
                    ) : (
                        <>
                            <Link to="/login" className="auth-btn login-btn">Log in</Link>
                            <Link to="/signup" className="auth-btn signup-btn">Sign up</Link>
                        </>
                    )}
                </nav>
            </header>

            <main className="home-hero" id="main-content" tabIndex={-1}>
                <div className="hero-copy">
                    <span className="hero-eyebrow">Portfolio tracking, simplified</span>
                    <h1 className="hero-title">
                        See your money <span className="hero-accent">move</span>.
                    </h1>
                    <p className="hero-subtitle">
                        Log your stock and crypto trades, see every holding in one place, and follow how
                        your portfolio's value changes over time — all in one calm, focused dashboard.
                    </p>
                    <div className="hero-actions">
                        <Link to={loggedIn ? "/dashboard" : "/signup"} className="auth-btn signup-btn large">
                            {loggedIn ? "Go to your dashboard" : "Create free account"}
                        </Link>
                        <button type="button" ref={demoButtonRef} className="hero-link-btn"
                                aria-haspopup="dialog" onClick={() => setDemoOpen(true)}>
                            <svg className="hero-play-icon" viewBox="0 0 20 20" aria-hidden="true">
                                <circle cx="10" cy="10" r="8.75" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                                <path d="M8.25 6.6v6.8l5.4-3.4z" fill="currentColor"/>
                            </svg>
                            See how it works
                        </button>
                    </div>

                    <div className="hero-stats">
                        {userCount >= 100 ? (
                            <div className="hero-stat">
                                <span className="hero-stat-value positive">{userCount.toLocaleString()}</span>
                                <span className="hero-stat-label">Investors tracking</span>
                            </div>
                        ) : (
                            <div className="hero-stat">
                                <span className="hero-stat-value positive">Free</span>
                                <span className="hero-stat-label">No credit card</span>
                            </div>
                        )}
                        <div className="hero-stat-divider"/>
                        <div className="hero-stat">
                            <span className="hero-stat-value">3</span>
                            <span className="hero-stat-label">Currencies: CAD, USD, EUR</span>
                        </div>
                        <div className="hero-stat-divider"/>
                        <div className="hero-stat">
                            <span className="hero-stat-value">ACB</span>
                            <span className="hero-stat-label">Canadian tax report</span>
                        </div>
                    </div>
                </div>

                <div className="hero-visual">
                    <div className="preview-card">
                        <div className="preview-card-header">
                            <span className="preview-label">Portfolio value</span>
                            <span className="range-pill active">1Y</span>
                        </div>
                        <div className="preview-value">CA$84,920.18</div>
                        <div className="preview-change positive">+CA$9,213.42 (+12.2%)</div>

                        <svg className="preview-chart" viewBox="0 0 320 120" preserveAspectRatio="none" aria-hidden="true">
                            <defs>
                                <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="0%" stopColor="rgba(59,130,246,0.35)"/>
                                    <stop offset="100%" stopColor="rgba(59,130,246,0)"/>
                                </linearGradient>
                            </defs>
                            <path
                                className="preview-fill"
                                d="M0,90 L20,85 L40,92 L60,70 L80,75 L100,60 L120,65 L140,45 L160,55 L180,38 L200,42 L220,28 L240,35 L260,20 L280,25 L300,10 L320,15 L320,120 L0,120 Z"
                                fill="url(#chartFill)"
                            />
                            {/* draws itself when the page opens (Home.css) */}
                            <path
                                className="preview-line"
                                pathLength="1"
                                d="M0,90 L20,85 L40,92 L60,70 L80,75 L100,60 L120,65 L140,45 L160,55 L180,38 L200,42 L220,28 L240,35 L260,20 L280,25 L300,10 L320,15"
                                fill="none"
                                stroke="#3b82f6"
                                strokeWidth="2"
                                vectorEffect="non-scaling-stroke"
                            />
                        </svg>

                        <div className="preview-holdings">
                            <div className="preview-holding-row">
                                <div className="preview-holding-name">
                                    <span className="ticker-dot aapl"/>
                                    <span>AAPL</span>
                                </div>
                                <span className="preview-holding-value">CA$12,480.00</span>
                                <span className="preview-holding-change positive">+1.8%</span>
                            </div>
                            <div className="preview-holding-row">
                                <div className="preview-holding-name">
                                    <span className="ticker-dot nvda"/>
                                    <span>NVDA</span>
                                </div>
                                <span className="preview-holding-value">CA$9,150.50</span>
                                <span className="preview-holding-change positive">+4.2%</span>
                            </div>
                            <div className="preview-holding-row">
                                <div className="preview-holding-name">
                                    <span className="ticker-dot btc"/>
                                    <span>BTC</span>
                                </div>
                                <span className="preview-holding-value">CA$6,310.90</span>
                                <span className="preview-holding-change negative">−0.6%</span>
                            </div>
                        </div>
                    </div>
                </div>
            </main>

            <section className="home-features" id="features" aria-labelledby="features-heading">
                <h2 id="features-heading" className="features-heading">Built for Canadian investors</h2>
                <div className="feature-card">
                    <span className="feature-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h16M6 16V9M10 16V5M14 16v-6M18 16V8"/></svg></span>
                    <h3>Canadian tax report</h3>
                    <p>Capital gains with your ACB pooled across years, settlement dates and possible superficial losses flagged, ready to download as a CSV. Informational, not tax advice.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg></span>
                    <h3>Import from your broker</h3>
                    <p>Bring in a Wealthsimple or Questrade activity export, check every row in a preview, then save them all at once.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/><circle cx="18" cy="17" r="2"/></svg></span>
                    <h3>TFSA, RRSP, FHSA and more</h3>
                    <p>Tag each trade with its account and see your allocation by account, asset type and currency.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg></span>
                    <h3>Market analyst</h3>
                    <p>A plain-language read on any stock or coin: trend, momentum, risk and typical price ranges, built from the numbers it shows. Not financial advice.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg></span>
                    <h3>Up-to-date prices</h3>
                    <p>Prices refresh each time you open a page, with charts from a day to all time. Market data can be delayed.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z"/><path d="M3 12h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9Z"/></svg></span>
                    <h3>Stocks and crypto, in your currency</h3>
                    <p>US and Canadian listings and thousands of coins in one portfolio, shown in CAD, USD or EUR.</p>
                </div>
            </section>

            <footer className="home-footer">
                <span className="footer-brand">
                    <img className="footer-mark" src="/zenith-logo.svg" alt="" width="16" height="16"/>
                    © 2026 Zenith Wallet Tracker
                </span>
                <span className="footer-dot">·</span>
                <span>Built for investors, by investors.</span>
                <span className="footer-dot">·</span>
                <Link to="/privacy" className="footer-link">Privacy &amp; disclaimer</Link>
                <span className="footer-dot">·</span>
                <Link to="/terms" className="footer-link">Terms</Link>
                <span className="footer-dot">·</span>
                <Link to="/support" className="footer-link">Support</Link>
            </footer>
        </div>

        {demoOpen && <DemoVideoModal onClose={closeDemo} loggedIn={loggedIn} returnFocusRef={demoButtonRef}/>}
        </>
    )
}

export default HomePage
