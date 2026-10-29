import {Link} from "react-router-dom";
import usePageTitle from "../utils/usePageTitle.js";
import {CONTACT_EMAIL} from "../utils/contact.js";
import LegalLayout from "../components/LegalLayout.jsx";
import {BRAND_NAME} from "../utils/brand.js";

// Public Terms of Use, linked from sign up (which says creating an account means agreeing to them), the sign in
// form, the policy pages and the app. Plain language on purpose. Update the date when the substance changes.
const EFFECTIVE_DATE = "October 22, 2026";

const SECTIONS = [
    ["agreement", "Agreeing to these terms"],
    ["service", "The service"],
    ["advice", "Not financial advice"],
    ["account", "Your account and records"],
    ["use", "Acceptable use"],
    ["data", "Third-party data"],
    ["termination", "Ending your account"],
    ["warranty", "No warranty"],
    ["liability", "Limitation of liability"],
    ["changes", "Changes"],
    ["law", "Governing law"],
    ["contact", "Contact"],
];

// The terms of use (public).
function TermsPage() {
    usePageTitle("Terms of Use");

    return (
        <LegalLayout sections={SECTIONS}>
            <header className="legal-header">
                <h1>Terms of Use</h1>
                <p className="legal-meta">Effective {EFFECTIVE_DATE}</p>
                <p>
                    These terms cover your use of {BRAND_NAME} ("Zenith", "we", "us"), the portfolio
                    tracker at zenithwalletracker.ca and in the Zenith iPhone app. They are written to be read, so
                    here is the short version:
                </p>
                <ul className="legal-summary">
                    <li>Zenith is free and provided "as is", without any warranty.</li>
                    <li>Nothing in Zenith is financial advice. Your investment decisions are your own.</li>
                    <li>Prices and other market data come from third parties and can be delayed or wrong.</li>
                    <li>Keep your own records; Zenith is not a replacement for your broker's statements.</li>
                    <li>Don't abuse, scrape or automate the service.</li>
                </ul>
            </header>

            <section id="agreement" className="legal-section">
                <h2>Agreeing to these terms</h2>
                <p>
                    By creating an account or using Zenith, you agree to these Terms of Use and to
                    our <Link to="/privacy">Privacy Policy</Link>, which explains what data we collect and how it
                    is used. If you don't agree, please don't use Zenith. You must be at least 13 years old to use
                    it.
                </p>
            </section>

            <section id="service" className="legal-section">
                <h2>The service</h2>
                <p>
                    Zenith lets you log the stock and cryptocurrency trades you make elsewhere and shows your
                    holdings, returns, price charts and an automated market analysis. Zenith does not hold money or
                    assets, does not connect to your bank or brokerage, and cannot buy or sell anything for you.
                </p>
                <p>
                    We may change, pause or stop any part of the service, including features, limits and the data
                    providers we use, at any time.
                </p>
            </section>

            <section id="advice" className="legal-section legal-callout">
                <h2>Not financial advice</h2>
                <p>
                    <strong>Nothing in Zenith is financial, investment, tax or legal advice</strong>, and nothing in
                    it is a recommendation to buy, sell or hold any asset. The Market Analyst is generated
                    automatically by software from public market data; no person reviews it and it does not know
                    your situation, goals or risk tolerance. Scenario price ranges describe past price movements and
                    are not predictions. Past performance does not guarantee future results.
                </p>
                <p>
                    You are solely responsible for your investment decisions. Consider speaking with a licensed
                    financial professional before making any. See the <Link to="/privacy#disclaimer">full
                    disclaimer</Link>.
                </p>
            </section>

            <section id="account" className="legal-section">
                <h2>Your account and records</h2>
                <ul>
                    <li>Give a real email address you can access, and keep your password private.</li>
                    <li>
                        You are responsible for what happens under your account. If you think someone else has
                        used it, change your password and use "Log out of all devices" on the Account page.
                    </li>
                    <li>
                        You are responsible for the trades you enter and for checking that they are accurate.
                        Zenith's holdings, returns and values are calculated from what you enter and from
                        third-party prices, and may not match your broker's records.
                    </li>
                    <li>
                        Keep your own records of your investments (for example your broker's statements and tax
                        documents). Zenith is not a record-keeping service for tax or legal purposes, and we don't
                        guarantee that data stored in Zenith will always be available.
                    </li>
                </ul>
            </section>

            <section id="use" className="legal-section">
                <h2>Acceptable use</h2>
                <p>When using Zenith, you agree not to:</p>
                <ul>
                    <li>
                        Access it with bots, scripts, scrapers or other automated means, or collect its data
                        (including prices, search results or analyst reports) in bulk.
                    </li>
                    <li>
                        Try to get around rate limits, security measures or access controls, or probe, scan or
                        test the service for weaknesses without our permission.
                    </li>
                    <li>Overload, disrupt or interfere with the service or other people's use of it.</li>
                    <li>Use someone else's account, or create accounts with addresses that aren't yours.</li>
                    <li>Use Zenith for anything illegal, or resell or redistribute it or its data.</li>
                </ul>
            </section>

            <section id="data" className="legal-section">
                <h2>Third-party data</h2>
                <p>
                    Prices, exchange rates, company information and other market data in Zenith come from third
                    parties, currently Yahoo Finance, TwelveData, CoinGecko and ExchangeRate-API. This data may be
                    delayed, incomplete or wrong, and a provider may stop offering it at any time. We don't
                    guarantee its accuracy, completeness or timeliness, and you should check important figures
                    with an official source before relying on them.
                </p>
                <p>
                    Cryptocurrency data is provided by CoinGecko. The CoinGecko API and the data it provides are
                    the property of CoinGecko and its licensors. CoinGecko provides them "as is", and CoinGecko is
                    not liable for any errors, delays or losses arising from their use in Zenith.
                </p>
            </section>

            <section id="termination" className="legal-section">
                <h2>Ending your account</h2>
                <p>
                    You can stop using Zenith at any time and delete your account and all of its data
                    from <em>Account → Delete account</em>. We may suspend or delete an account that breaks these
                    terms, puts the service or other users at risk, or that was never verified (unverified accounts
                    are removed automatically after 7 days). We may also end the service as a whole; if we do, we
                    will try to give reasonable notice so you can keep a copy of your records.
                </p>
            </section>

            <section id="warranty" className="legal-section">
                <h2>No warranty</h2>
                <p>
                    Zenith is provided <strong>"as is" and "as available"</strong>, without warranties of any kind,
                    express or implied, including that it will be accurate, reliable, secure, uninterrupted, free
                    of errors or fit for a particular purpose, to the fullest extent the law allows.
                </p>
            </section>

            <section id="liability" className="legal-section">
                <h2>Limitation of liability</h2>
                <p>
                    To the fullest extent the law allows, we are not liable for any indirect, incidental, special
                    or consequential losses, or for any loss of money, profits, investments or data, arising from
                    your use of Zenith or your reliance on anything it shows, including market data, calculations
                    and Market Analyst reports. Zenith is a free service, and our total liability for any claim
                    relating to it is limited to the amount you paid us to use it, which is zero. Nothing in these
                    terms limits rights you have under consumer protection laws that can't be waived.
                </p>
            </section>

            <section id="changes" className="legal-section">
                <h2>Changes</h2>
                <p>
                    We may update these terms. When we do, we will change the effective date at the top of this
                    page, and for significant changes we will let users know in the app or by email. Continuing to
                    use Zenith after a change means you accept the updated terms.
                </p>
            </section>

            <section id="law" className="legal-section">
                <h2>Governing law</h2>
                <p>
                    These terms are governed by the laws of Canada. If any part of them is found to be
                    unenforceable, the rest still applies.
                </p>
            </section>

            <section id="contact" className="legal-section">
                <h2>Contact</h2>
                <p>
                    Questions about these terms? Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
                    For help with your account, see the <Link to="/support">Support</Link> page.
                </p>
            </section>
        </LegalLayout>
    );
}

export default TermsPage;
