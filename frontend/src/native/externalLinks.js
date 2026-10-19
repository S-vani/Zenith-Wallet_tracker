import {isNative, loadPlugin} from "./platform.js";

const browserPlugin = loadPlugin(() => import("@capacitor/browser"));

// The address to open in the in-app browser for a link to another website, or null to leave the click alone:
// links inside the app, mailto: (opens Mail), tel: and anything that isn't a web page.
export function externalUrl(href, appOrigin) {
    if (!href) return null;
    let url;
    try {
        url = new URL(href, appOrigin);
    } catch {
        return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (url.origin === appOrigin) return null;
    return url.href;
}

// Links to other sites (analyst sources, the data credits, Google's policies...) open in an in-app Safari sheet
// (SFSafariViewController) instead of leaving Zenith for Safari. One capture-phase listener, so no link component
// needs to know about the app. No-op on the website, where target="_blank" opens a new tab as usual.
export function openLinksInAppBrowser() {
    if (!isNative) return;
    document.addEventListener("click", (e) => {
        const link = e.target.closest?.("a[href]");
        if (!link || e.defaultPrevented) return;
        const url = externalUrl(link.href, window.location.origin);
        if (!url) return;
        e.preventDefault();
        e.stopPropagation();
        browserPlugin()
            .then(({Browser}) => Browser.open({url, toolbarColor: "#060a12"}))
            .catch(() => window.open(url, "_blank")); // plugin missing: Safari is still better than nothing
    }, true);
}
