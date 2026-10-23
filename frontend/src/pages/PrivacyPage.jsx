import {Link} from "react-router-dom";
import usePageTitle from "../utils/usePageTitle.js";
import {CONTACT_EMAIL} from "../utils/contact.js";
import LegalLayout from "../components/LegalLayout.jsx";

// Shown publicly and required by the app stores. Keep it in step with what the app actually collects and sends.
const EFFECTIVE_DATE = "October 22, 2026";

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

    return (
        <LegalLayout sections={SECTIONS}>
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
                    If you choose "Continue with Google" on the website, Google shares your name, email address
                    and Google account ID with us so your Google login stays linked to your Zenith account. We
                    use Google's sign-in token only during that sign-in and don't store it, and we never get
                    your Google password.
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
                    browser type, the page requested and the time) to keep the service running and secure. The
                    page address can include what you searched for (for example a ticker symbol). To keep you
                    signed in, a login token is stored on your device: in your browser's local storage on the
                    website, and in the iPhone app's own storage with a copy in the iOS Keychain. The iPhone app
                    also sends its version number with each request, so we can tell you when an update is
                    required. We do not use advertising or tracking cookies.
                </p>
                <h3>On your iPhone</h3>
                <p>
                    If you turn on the Face ID lock, Face ID is handled entirely by iOS: we never receive or
                    store your face data, only whether the check succeeded. So the app can show your portfolio
                    without a connection, it keeps a copy of your most recently loaded screens on your phone;
                    signing out or deleting your account removes it.
                </p>
                <p>
                    In the app, links to other websites (such as a Market Analyst source or our data
                    providers) open in an in-app browser (Apple's Safari View Controller) without leaving
                    Zenith. That website receives your visit like any other browser visit (including your IP
                    address), its own privacy policy applies there, and we can't see what you do on it.
                </p>
            </section>

            <section id="use" className="legal-section">
                <h2>How we use it</h2>
                <ul>
                    <li>To create your account, sign you in, verify your email address and reset your password when you ask.</li>
                    <li>
                        To send security notices: if your email address is changed we tell the old address, and
                        if your password is changed on the Account page we email the address on your account,
                        so you would notice a change you didn't make.
                    </li>
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
                        exchange rate service): the symbols and currencies being looked up, including the
                        symbols of assets you hold so we can price them. These requests come from our servers,
                        so the providers never receive your name, email, IP address or quantities, and can't
                        link a symbol to you.
                    </li>
                    <li>
                        <strong>CoinGecko coin logos</strong>: the small logos next to cryptocurrencies in
                        search results load directly from CoinGecko's image servers, so CoinGecko can see your
                        IP address and which coin logos were shown. No account details are sent.
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
                        <strong>Email delivery</strong>: verification, password reset and security notice emails
                        are sent through an email delivery provider (currently Google Gmail), so your email address
                        (and, for an email change, your old and new addresses) and the message pass through it.
                    </li>
                    <li>
                        <strong>Vultr</strong>: our servers and database run on Vultr, a cloud hosting
                        provider.
                    </li>
                </ul>
                <p>
                    We only share what each service needs to do its job for us, and we use providers that
                    protect that information to the same or a greater degree than this policy. These providers
                    may process data outside your province or country. We may also disclose information if the
                    law requires it.
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
                    We keep your account and transactions for as long as your account exists. You can edit or
                    delete individual transactions at any time on the Transactions page. If you sign up but
                    never verify your email address, the account and anything attached to it are deleted
                    automatically after 7 days.
                </p>
                <p>
                    <strong>To delete your account</strong>, open <em>Account → Delete account</em> in the app.
                    This permanently removes your account, every transaction you logged and any linked Google
                    sign-in from our database straight away, and it cannot be undone. Market Analyst reports
                    are shared per asset rather than per person, so they contain no personal information and
                    are not affected. You can also ask us to delete your data by emailing us (see{" "}
                    <a href="#contact">Contact</a>).
                </p>
                <p>
                    Web server logs, including any search terms in them, are kept for up to 14 days and then
                    deleted automatically. Server backups, if any, are kept for no more than 30 days, so deleted
                    data also disappears from them within that time.
                </p>
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
                    <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. Answers to common questions
                    (verifying your email, resetting your password, deleting your account) are on
                    the <Link to="/support">Support</Link> page, and the rules for using Zenith are in
                    our <Link to="/terms">Terms of Use</Link>.
                </p>
            </section>
        </LegalLayout>
    );
}

export default PrivacyPage;
