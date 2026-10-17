import {Capacitor} from "@capacitor/core";

// true inside the iOS app (Capacitor), false on the website. Every native feature checks this first,
// so none of it runs (or even downloads its plugin code) for website visitors.
export const isNative = Capacitor.isNativePlatform();

// Plugins are loaded on first use so the website bundle doesn't carry them
export function loadPlugin(importer) {
    let promise;
    return () => (promise ??= importer());
}
