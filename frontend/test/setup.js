/* global process */
// The formatters use the reader's locale and time zone (Intl with `undefined`), which differ between machines.
// Pin them so the expected strings in the tests are the same everywhere.
process.env.TZ = "America/Toronto";

const LOCALE = "en-US";

const RealNumberFormat = Intl.NumberFormat;

function PinnedNumberFormat(locales, options) {
    return new RealNumberFormat(locales ?? LOCALE, options);
}

PinnedNumberFormat.prototype = RealNumberFormat.prototype;
PinnedNumberFormat.supportedLocalesOf = RealNumberFormat.supportedLocalesOf;
Intl.NumberFormat = PinnedNumberFormat;

const realNumberToLocale = Number.prototype.toLocaleString;
Number.prototype.toLocaleString = function (locales, options) {
    return realNumberToLocale.call(this, locales ?? LOCALE, options);
};

const realDateToLocale = Date.prototype.toLocaleString;
Date.prototype.toLocaleString = function (locales, options) {
    return realDateToLocale.call(this, locales ?? LOCALE, options);
};
