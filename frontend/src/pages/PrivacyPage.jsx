import {useEffect} from "react";
import {Link, useLocation} from "react-router-dom";
import {getToken} from "../services/api.js";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Home.css";
import "../css/Legal.css";

// Shown publicly and required by the app stores. Keep it in step with what the app actually collects and sends.
const EFFECTIVE_DATE = "October 16, 2026";
const CONTACT_EMAIL = "shayan.vanishoja86@gmail.com";

const SECTIONS = [
    ["disclaimer", "Not financial advice"],
    ["collect", "Information we collect"],
    ["use", "How we use it"],
    ["services", "Services we rely on"],
    ["never", "What we never do"],
    ["retention", "Keeping and deleting your data"],
    ["security", "Security"],
    ["rights", "Your choices and rights"],
    ["children", "Children"],
    ["changes", "Changes to this policy"],
    ["contact", "Contact"],
];

function PrivacyPage() {
    usePageTitle("Privacy Policy & Disclaimer");
    const {hash} = useLocation();
    const loggedIn = Boolean(getToken());

    // links like /privacy#disclaimer should land on that section
    useEffect(() => {
        if (!hash) return;
        document.getElementById(hash.slice(1))?.scrollIntoView();
    }, [hash]);

    return (
        <div className="home-page legal-page">
            <header className="home-topbar">
                <Link to="/" className="home-brand">
                    <img className="brand-mark" src="/zenith-logo.svg" alt="" width="32" height="32"/>
                    <span className="brand-name">Zenith&nbsp;<span className="brand-accent">Wallet Tracker</span></span>
                </Link>
                <nav className="home-auth" aria-label="Account">
                    <Link to={loggedIn ? "/dashboard" : "/"} className="auth-btn login-btn">
                        {loggedIn ? "Back to the app" : "Back to home"}
                    </Link>
                </nav>
            </header>

            <main className="legal-layout">
                <aside className="legal-toc" aria-label="On this page">
                    <span className="legal-toc-title">On this page</span>
                    {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
                </aside>

                <article className="legal-content">
                    <header className="legal-header">
                        <h1>Privacy Policy &amp; Disclaimer</h1>
                        <p className="legal-meta">Effective {EFFECTIVE_DATE}</p>
                        <p>
                            Zenith Wallet Tracker ("Zenith", "we", "us") is a portfolio tracking app available at
                            zenithwalletracker.ca and, where available, as a mobile app. This page explains what information we
                            collect, why, who it is shared with, and how to delete it. It also explains the limits of
                            the market information Zenith shows you.
                        </p>
                        <ul className="legal-summary">
                            <li>We collect only what the app needs: your account details and the transactions you enter.</li>
                            <li>We don't sell your data, show ads or use tracking or analytics tools.</li>
                            <li>You can delete your account and all of its data at any time from the Account page.</li>
                            <li>Nothing in Zenith, including the Market Analyst, is financial advice.</li>
                        </ul>
                    </header>

                    <section id="disclaimer" className="legal-section legal-callout">
                        <h2>Not financial advice</h2>
                        <p>
                            Zenith is an information and record-keeping tool. <strong>Nothing in Zenith is financial,
                            investment, tax or legal advice</strong>, and nothing in it is a recommendation or offer to
                            buy, sell or hold any stock, cryptocurrency or other asset.
                        </p>
                        <p>
                            <strong>The Market Analyst is generated automatically.</strong> Its outlooks
                            (bullish, neutral or bearish), confidence levels, insights, "what to watch" items and bull,
                            base and bear scenarios are produced by software. A set of fixed rules is applied to public
                            market data, and when enabled, an AI language model (Google Gemini) may reword the text. No
                            person reviews these reports, and they do not take your personal situation, goals or risk
                            tolerance into account.
                        </p>
                        <ul>
                            <li>
                                Scenario price ranges describe how far prices have typically moved in the past. They
                                are not predictions or price targets.
                            </li>
                            <li>
                                Market data comes from third parties and can be delayed, incomplete or wrong. Prices,
                                returns and portfolio values shown in Zenith may not match your broker's records.
                            </li>
                            <li>Past performance does not guarantee future results. Investing involves risk, including loss of money.</li>
                            <li>
                                Analyst ratings and price targets shown for stocks are other people's opinions,
                                reported as published.
                            </li>
                        </ul>
                        <p>
                            You are responsible for your own investment decisions. Consider speaking with a licensed
                            financial professional before making any. Zenith is provided "as is", and to the extent the
                            law allows, we are not liable for losses arising from its use.
                        </p>
                    </section>

                    <section id="collect" className="legal-section">
                        <h2>Information we collect</h2>
                        <h3>Account information</h3>
                        <p>
                            When you sign up we store your name, email address, preferred currency (CAD, USD or EUR),
                            the date you joined and whether your email is verified. Your password is never stored in
                            readable form, only as a one-way cryptographic hash.
                        </p>
                        <h3>Google sign-in</h3>
                        <p>
                            If you choose "Continue with Google", Google shares your name, email address and Google
                            account ID with us, and we store the access token Google returns so your Google login stays
                            linked to your Zenith account. We do not get your Google password.
                        </p>
                        <h3>Portfolio information</h3>
                        <p>
                            The transactions you log (symbol, buy or sell, quantity, price and date) are stored so we
                            can calculate your holdings, returns and charts. Zenith does not connect to your bank or
                            brokerage, and we never ask for account numbers.
                        </p>
                        <h3>Technical information</h3>
                        <p>
                            Like most websites, our web server keeps standard request logs (such as IP address,
                            browser type, the page requested and the time) to keep the service running and secure. To
                            keep you signed in, the app stores a login token on your device (in your browser's local
                            storage or the app's storage). We do not use advertising or tracking cookies.
                        </p>
                    </section>

                    <section id="use" className="legal-section">
                        <h2>How we use it</h2>
                        <ul>
                            <li>To create your account, sign you in and verify your email address.</li>
                            <li>To show your holdings, returns, charts and transaction history in your chosen currency.</li>
                            <li>To generate Market Analyst reports and limit how often they can be refreshed.</li>
                            <li>To keep the service secure, fix problems and prevent abuse.</li>
                            <li>To show a total user count on the home page (a number only, with no personal details).</li>
                        </ul>
                    </section>

                    <section id="services" className="legal-section">
                        <h2>Services we rely on</h2>
                        <p>Zenith uses these third-party services. Each one receives only what is listed:</p>
                        <ul>
                            <li>
                                <strong>Market data</strong> (Yahoo Finance, TwelveData, CoinGecko and the open.er-api
                                exchange rate service): the symbols and currencies being looked up. They never receive
                                your name, email or portfolio.
                            </li>
                            <li>
                                <strong>Google Gemini</strong> (only if AI rewording is enabled): the text and numbers
                                of a Market Analyst report about a stock or coin. No personal information or portfolio
                                data is sent.
                            </li>
                            <li>
                                <strong>Google sign-in</strong>: used only if you choose it. Google's own privacy
                                policy applies to your Google account.
                            </li>
                            <li>
                                <strong>Gmail</strong>: verification emails are sent through Google's email service,
                                so your email address passes through it.
                            </li>
                            <li>
                                <strong>Google Fonts</strong>: your browser downloads the site's font from Google, which
                                can see your IP address.
                            </li>
                            <li>
                                <strong>Vultr</strong>: our servers and database run on Vultr, a cloud hosting
                                provider.
                            </li>
                        </ul>
                        <p>
                            These providers may process data outside your province or country. We may also disclose
                            information if the law requires it.
                        </p>
                    </section>

                    <section id="never" className="legal-section">
                        <h2>What we never do</h2>
                        <ul>
                            <li>Sell or rent your personal information.</li>
                            <li>Show ads or share your data with advertisers or data brokers.</li>
                            <li>Use third-party analytics or tracking tools.</li>
                            <li>Share your portfolio with other users.</li>
                        </ul>
                    </section>

                    <section id="retention" className="legal-section">
                        <h2>Keeping and deleting your data</h2>
                        <p>
                            We keep your account and transactions for as long as your account exists. You can delete
                            individual transactions at any time.
                        </p>
                        <p>
                            <strong>To delete your account</strong>, open <em>Account → Delete account</em> in the app.
                            This permanently removes your account, every transaction you logged and any linked Google
                            sign-in from our database straight away, and it cannot be undone. Market Analyst reports
                            are shared per asset rather than per person, so they contain no personal information and
                            are not affected. You can also ask us to delete your data by emailing us (see{" "}
                            <a href="#contact">Contact</a>).
                        </p>
                        <p>Web server logs are kept only as long as needed to run and secure the service.</p>
                    </section>

                    <section id="security" className="legal-section">
                        <h2>Security</h2>
                        <p>
                            Connections to Zenith are encrypted with HTTPS, passwords are stored only as hashes, and
                            API keys for our data providers stay on our servers. No online service can be guaranteed
                            100% secure, so please use a strong password that you don't use anywhere else.
                        </p>
                    </section>

                    <section id="rights" className="legal-section">
                        <h2>Your choices and rights</h2>
                        <ul>
                            <li><strong>Access and correction:</strong> view and edit your name, email and currency on the Account page.</li>
                            <li><strong>Deletion:</strong> delete your account in the app at any time.</li>
                            <li>
                                <strong>Questions or requests:</strong> contact us for a copy of your data or about
                                anything in this policy.
                            </li>
                        </ul>
                        <p>
                            Depending on where you live (for example under Canada's PIPEDA, the EU and UK GDPR or
                            California's CCPA), you may have additional rights. We will respond to requests within the
                            time the law requires.
                        </p>
                    </section>

                    <section id="children" className="legal-section">
                        <h2>Children</h2>
                        <p>
                            Zenith is not intended for children under 13, and we do not knowingly collect their
                            information. If you believe a child has created an account, contact us and we will delete it.
                        </p>
                    </section>

                    <section id="changes" className="legal-section">
                        <h2>Changes to this policy</h2>
                        <p>
                            If we change this policy, we will update the effective date at the top of this page. If the
                            changes are significant, we will let users know in the app or by email.
                        </p>
                    </section>

                    <section id="contact" className="legal-section">
                        <h2>Contact</h2>
                        <p>
                            For privacy questions, data requests or anything else about this policy, email{" "}
                            <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
                        </p>
                    </section>
                </article>
            </main>

            <footer className="home-footer">
                <span className="footer-brand">
                    <img className="footer-mark" src="/zenith-logo.svg" alt="" width="16" height="16"/>
                    © 2026 Zenith Wallet Tracker
                </span>
            </footer>
        </div>
    );
}

export default PrivacyPage;
