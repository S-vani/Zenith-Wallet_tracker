import {Link} from "react-router-dom";
import {getToken, getUserCount} from "../services/api.js";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css"
import {useEffect, useState} from "react";

function HomePage() {
    usePageTitle(null);
    const [userCount, setUserCount] = useState(null);
    const loggedIn = Boolean(getToken());

    useEffect(() => {
        getUserCount().then(setUserCount).catch(() => null);
    }, []);


    return (
        <div className="home-page">
            <header className="home-topbar">
                <Link to="/" className="home-brand">
                    <span className="brand-mark">◆</span>
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

            <main className="home-hero">
                <div className="hero-copy">
                    <span className="hero-eyebrow">Portfolio tracking, simplified</span>
                    <h1 className="hero-title">
                        See your money <span className="hero-accent">move</span>.
                    </h1>
                    <p className="hero-subtitle">
                        Track holdings, log transactions, and watch your net worth
                        evolve in real time — all in one calm, focused dashboard.
                    </p>
                    <div className="hero-actions">
                        <Link to={loggedIn ? "/dashboard" : "/signup"} className="auth-btn signup-btn large">
                            {loggedIn ? "Go to your dashboard" : "Create free account"}
                        </Link>
                        <a href="#features" className="hero-link-btn">See how it works →</a>
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
                            <span className="hero-stat-value">24/7</span>
                            <span className="hero-stat-label">Live market sync</span>
                        </div>
                        <div className="hero-stat-divider"/>
                        <div className="hero-stat">
                            <span className="hero-stat-value">0</span>
                            <span className="hero-stat-label">Spreadsheets needed</span>
                        </div>
                    </div>
                </div>

                <div className="hero-visual">
                    <div className="preview-card">
                        <div className="preview-card-header">
                            <span className="preview-label">Portfolio value</span>
                            <span className="range-pill active">1Y</span>
                        </div>
                        <div className="preview-value">$84,920.18</div>
                        <div className="preview-change positive">+ $9,213.42 (12.2%)</div>

                        <svg className="preview-chart" viewBox="0 0 320 120" preserveAspectRatio="none" aria-hidden="true">
                            <defs>
                                <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="0%" stopColor="rgba(59,130,246,0.35)"/>
                                    <stop offset="100%" stopColor="rgba(59,130,246,0)"/>
                                </linearGradient>
                            </defs>
                            <path
                                d="M0,90 L20,85 L40,92 L60,70 L80,75 L100,60 L120,65 L140,45 L160,55 L180,38 L200,42 L220,28 L240,35 L260,20 L280,25 L300,10 L320,15 L320,120 L0,120 Z"
                                fill="url(#chartFill)"
                            />
                            <path
                                d="M0,90 L20,85 L40,92 L60,70 L80,75 L100,60 L120,65 L140,45 L160,55 L180,38 L200,42 L220,28 L240,35 L260,20 L280,25 L300,10 L320,15"
                                fill="none"
                                stroke="#3b82f6"
                                strokeWidth="2"
                            />
                        </svg>

                        <div className="preview-holdings">
                            <div className="preview-holding-row">
                                <div className="preview-holding-name">
                                    <span className="ticker-dot aapl"/>
                                    <span>AAPL</span>
                                </div>
                                <span className="preview-holding-value">$12,480.00</span>
                                <span className="preview-holding-change positive">+1.8%</span>
                            </div>
                            <div className="preview-holding-row">
                                <div className="preview-holding-name">
                                    <span className="ticker-dot nvda"/>
                                    <span>NVDA</span>
                                </div>
                                <span className="preview-holding-value">$9,150.50</span>
                                <span className="preview-holding-change positive">+4.2%</span>
                            </div>
                            <div className="preview-holding-row">
                                <div className="preview-holding-name">
                                    <span className="ticker-dot btc"/>
                                    <span>BTC</span>
                                </div>
                                <span className="preview-holding-value">$6,310.90</span>
                                <span className="preview-holding-change negative">-0.6%</span>
                            </div>
                        </div>
                    </div>
                </div>
            </main>

            <section className="home-features" id="features">
                <div className="feature-card">
                    <span className="feature-icon">⟳</span>
                    <h3>Real-time tracking</h3>
                    <p>Prices and balances update automatically, so your dashboard always reflects the market.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon">▤</span>
                    <h3>Unified holdings</h3>
                    <p>Stocks, crypto, and cash in one view, with breakdowns that show where your money sits.</p>
                </div>
                <div className="feature-card">
                    <span className="feature-icon">↗</span>
                    <h3>Transaction history</h3>
                    <p>Every buy, sell, and transfer logged and searchable, so nothing slips through the cracks.</p>
                </div>
            </section>

            <footer className="home-footer">
                <span>© 2026 Zenith Wallet Tracker</span>
                <span className="footer-dot">·</span>
                <span>Built for investors, by investors.</span>
            </footer>
        </div>
    )
}

export default HomePage
