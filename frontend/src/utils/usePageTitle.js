import {useEffect} from "react";

const SITE = "https://zenithwalletracker.ca";
const HOME_TITLE = "Zenith Wallet Tracker – Free Stock & Crypto Portfolio Tracker";

// What search engines should show for the public pages. Every other route (the signed-in app, one-time links, 404s)
// is marked noindex: crawlers only ever see a login page there.
const PUBLIC_PAGES = {
    "/": "Zenith Wallet Tracker is a free stock and crypto portfolio tracker. Log your trades, follow your holdings and returns in CAD, USD or EUR, and get a rules-based market outlook.",
    "/signup": "Create a free Zenith Wallet Tracker account and track your stocks and crypto in one place.",
    "/login": "Log in to Zenith Wallet Tracker to see your stock and crypto portfolio, holdings and returns.",
    "/privacy": "How Zenith Wallet Tracker handles your data, and why its market analysis is not financial advice.",
    "/terms": "The terms of use for Zenith Wallet Tracker, the free stock and crypto portfolio tracker.",
    "/support": "Help with Zenith Wallet Tracker: contact us, verify your email, reset your password, change currency or delete your account.",
};

function setMeta(selector, create, value) {
    let element = document.head.querySelector(selector);
    if (!element) {
        element = create();
        document.head.appendChild(element);
    }
    element.setAttribute(element.tagName === "LINK" ? "href" : "content", value);
}

export default function usePageTitle(title) {
    useEffect(() => {
        document.title = title ? `${title} · Zenith Wallet Tracker` : HOME_TITLE;

        const path = window.location.pathname.replace(/\/+$/, "") || "/";
        const description = PUBLIC_PAGES[path];
        const make = (tag, attr, value) => () => Object.assign(document.createElement(tag), {[attr]: value});

        setMeta('meta[name="robots"]', make("meta", "name", "robots"), description ? "index, follow" : "noindex");
        if (description) {
            setMeta('meta[name="description"]', make("meta", "name", "description"), description);
            setMeta('link[rel="canonical"]', make("link", "rel", "canonical"), `${SITE}${path === "/" ? "/" : path}`);
        } else {
            // a noindex page shouldn't point at the previous page as its canonical address
            document.head.querySelector('link[rel="canonical"]')?.remove();
        }
    }, [title]);
}
