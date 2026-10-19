import {isNative} from "./platform.js";

// The iPhone app opens on the Dashboard, so like a native tab bar its first tab is the screen it starts on.
// The website's order (Search first) is left exactly as it is.
export function tabOrder(links, native = isNative) {
    if (!native) return links;
    const first = links.filter((link) => link.to === "/dashboard");
    return [...first, ...links.filter((link) => link.to !== "/dashboard")];
}
