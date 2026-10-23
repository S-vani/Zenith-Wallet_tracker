import {Link} from "react-router-dom";
import usePageTitle from "../utils/usePageTitle.js";
import {CONTACT_EMAIL} from "../utils/contact.js";
import LegalLayout from "../components/LegalLayout.jsx";

// Public help page. App Store Connect requires a Support URL (https://zenithwalletracker.ca/support), so this must
// stay reachable without an account. Keep the answers in step with the app's actual screens and wording.
const SECTIONS = [
    ["contact", "Contact us"],
    ["verify", "Verifying your email"],
    ["password", "Resetting your password"],
    ["currency", "Changing your currency"],
    ["delete", "Deleting your account"],
    ["face-id", "Face ID lock (iPhone app)"],
    ["prices", "Where prices come from"],
    ["advice", "Not financial advice"],
];

function SupportPage() {
    usePageTitle("Support");

    return (
        <LegalLayout sections={SECTIONS}>
            <header className="legal-header">
                <h1>Support</h1>
                <p>
                    Help with Zenith Wallet Tracker on the website and in the iPhone app. If your question isn't
                    answered here, email us and we'll get back to you.
                </p>
            </header>

            <section id="contact" className="legal-section">
                <h2>Contact us</h2>
                <p>
                    Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. Please include the email address
                    of your Zenith account and, for a problem, what you were doing and whether it was on the website
                    or in the app. Never send us your password: we will never ask for it.
                </p>
            </section>

            <section id="verify" className="legal-section">
                <h2>Verifying your email</h2>
                <p>
                    After you sign up we email you a verification link. Open it, tap <em>Verify my email</em>, then
                    log in. The link opens in your browser; if you signed up in the iPhone app, go back to the app
                    afterwards (on an iPhone the page also offers an <em>Open the Zenith app</em> button).
                </p>
                <ul>
                    <li>
                        No email? Check your spam folder. You can ask for a new link with <em>Resend email</em> after
                        signing up, or with <em>Resend verification email</em> when you try to log in.
                    </li>
                    <li>Accounts that are never verified are deleted automatically after 7 days, so you can sign up again.</li>
                </ul>
            </section>

            <section id="password" className="legal-section">
                <h2>Resetting your password</h2>
                <p>
                    On the log in screen, choose <em>Forgot password?</em> and enter your email address. We email
                    you a link (if an account exists for that address); open it and choose a new password of at
                    least 8 characters. Resetting your password signs you out on every device.
                </p>
                <p>
                    Signed up with Google on the website? You can use the same steps to set a password, which you
                    need to sign in to the iPhone app.
                </p>
            </section>

            <section id="currency" className="legal-section">
                <h2>Changing your currency</h2>
                <p>
                    Open the <em>Account</em> tab, pick CAD, USD or EUR under <em>Currency</em> and save. All prices
                    and totals are then shown in that currency. Your trades keep the price you entered, so changing
                    currency doesn't change your records.
                </p>
            </section>

            <section id="delete" className="legal-section">
                <h2>Deleting your account</h2>
                <p>
                    Open the <em>Account</em> tab and choose <em>Delete account</em>, then confirm by typing DELETE
                    and your current password. This permanently deletes your account, every trade you logged and any linked Google
                    sign-in straight away; it can't be undone. If your account has no password yet (Google
                    sign-in), set one first with <a href="#password">Forgot password?</a>. You can also email us
                    to ask for your account to be deleted. See the <Link to="/privacy#retention">Privacy
                    Policy</Link> for details.
                </p>
            </section>

            <section id="face-id" className="legal-section">
                <h2>Face ID lock (iPhone app)</h2>
                <p>
                    In the app, open <em>Account</em> and turn on the lock under <em>Security</em>. Zenith then asks
                    for Face ID (or Touch ID, or your passcode if neither is set up) when you come back to the app,
                    and hides your portfolio in the app switcher. Face ID is handled by iOS: we never see your face
                    data. Signing out turns the lock off.
                </p>
            </section>

            <section id="prices" className="legal-section">
                <h2>Where prices come from</h2>
                <ul>
                    <li>Stock and ETF prices come from Yahoo Finance; stock search uses TwelveData.</li>
                    <li>Cryptocurrency prices come from Yahoo Finance and CoinGecko.</li>
                    <li>Currency conversion uses rates from ExchangeRate-API, refreshed about every hour.</li>
                </ul>
                <p>
                    Prices are the latest available close and may be delayed. When no price is available for an
                    asset, Zenith shows "—" and leaves it out of your totals instead of guessing.
                </p>
            </section>

            <section id="advice" className="legal-section legal-callout">
                <h2>Not financial advice</h2>
                <p>
                    Zenith, including the automated Market Analyst, is an information and record-keeping tool,
                    not financial advice. Read the <Link to="/privacy#disclaimer">full disclaimer</Link>, our{" "}
                    <Link to="/privacy">Privacy Policy</Link> and our <Link to="/terms">Terms of Use</Link>.
                </p>
            </section>
        </LegalLayout>
    );
}

export default SupportPage;
