// "Scan a screenshot" in the add-trade dialog: the text of a trade confirmation (Wealthsimple, Crypto.com...) is read
// on the device (textReader.js), turned into fields (tradeTextParser.js) and checked by the server (POST
// /transactions/scan/fields), or, as an optional fallback, the image is read by the server's AI (POST
// /transactions/scan, Google Gemini). The add form then opens prefilled. Nothing is saved from here: the user checks
// every field and saves the trade themselves. Pure helpers (tested in test/scan.test.js), except shrinkImage, which
// needs a browser's canvas.

import {formatPrice, formatQuantity, priceInputValue} from "../utils/format.js";
import {normalizeAccountType} from "../utils/accounts.js";
import {quantityInputValue, toLocalInputValue} from "./tradeForm.js";

// a phone photo can be 10+ MB; anything bigger than this is almost certainly not a screenshot, and decoding it could
// run a phone out of memory
export const MAX_PICK_BYTES = 20 * 1024 * 1024;

// the server's AI reading refuses images over 2.5 MB (413); a little under it, in case the server counts in decimal
// megabytes. Reading on the device has no limit, but the same small JPEG is quicker to read too.
const MAX_UPLOAD_BYTES = 2_500_000;

// plenty for the small text of a confirmation, and a 2000px JPEG stays far under the upload limit
const MAX_SIDE = 2000;
const JPEG_QUALITY = 0.85;

// some browsers give HEIC photos (and files from "Choose File") an empty type, so the extension decides then
const IMAGE_NAME = /\.(png|jpe?g|webp|heic|heif|gif|bmp|tiff?)$/i;

// Whether a picked file is an image (by its type, or its name when the browser gave no type).
export function isImageFile(file) {
    if (!file) return false;
    const type = String(file.type ?? "");
    if (type) return type.startsWith("image/");
    return IMAGE_NAME.test(String(file.name ?? ""));
}

// The picked image redrawn on a canvas, longest side at most 2000px, as a JPEG. Keeps uploads small on slow phone
// connections and drops the photo's EXIF data (location, device) on the way, since only the pixels are copied.
// A browser that can't decode the file (e.g. HEIC outside Safari) sends the original, which the server also accepts,
// as long as it fits under its limit.
export async function shrinkImage(file) {
    if (!file) throw new Error("Choose a screenshot to scan.");
    if (!isImageFile(file)) throw new Error("That file isn't an image. Choose a screenshot (PNG, JPEG or HEIC).");
    if (file.size > MAX_PICK_BYTES) {
        throw new Error("That image is over 20 MB. Choose a screenshot, or crop the photo first.");
    }

    let shrunk;
    try {
        shrunk = await redraw(file);
    } catch {
        shrunk = null; // couldn't decode or encode: try the original
    }
    if (shrunk) return shrunk;
    if (file.size > MAX_UPLOAD_BYTES) {
        throw new Error("This image is over 2.5 MB and this browser can't shrink it. Take a screenshot of it, " +
            "or crop it first.");
    }
    return file;
}

// Decodes the image and draws it scaled into a JPEG Blob, or null when the browser can't.
async function redraw(file) {
    const url = URL.createObjectURL(file);
    try {
        const img = new Image();
        img.src = url;
        await img.decode(); // an <img> applies the photo's EXIF rotation, so a sideways photo comes out upright
        const longest = Math.max(img.naturalWidth, img.naturalHeight);
        if (!longest) return null;
        const scale = Math.min(1, MAX_SIDE / longest);
        const width = Math.max(1, Math.round(img.naturalWidth * scale));
        const height = Math.max(1, Math.round(img.naturalHeight * scale));

        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) return null;
        // JPEG has no transparency: a see-through PNG would otherwise turn black behind dark text
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);

        const encode = (quality) => new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
        let blob = await encode(JPEG_QUALITY);
        if (blob && blob.size > MAX_UPLOAD_BYTES) blob = await encode(0.7); // a very busy photo
        canvas.width = 0; // iOS holds on to a canvas's memory until it's resized
        canvas.height = 0;
        return blob && blob.size > 0 && blob.size <= MAX_UPLOAD_BYTES ? blob : null;
    } finally {
        URL.revokeObjectURL(url);
    }
}

// Sending a screenshot to a third-party AI ("Try AI reading") needs a clear yes first (App Store guideline 5.1.2(i)).
// Reading on the device sends no image, so it isn't asked then. Asked once per device; storage can be missing or throw (private mode, blocked site data), and then it's simply asked each time.
const CONSENT_KEY = "scanConsent";

// Whether the user already agreed on this device.
export function hasScanConsent() {
    try {
        return globalThis.localStorage?.getItem(CONSENT_KEY) === "yes";
    } catch {
        return false;
    }
}

// Remembers the user's yes on this device.
export function saveScanConsent() {
    try {
        globalThis.localStorage?.setItem(CONSENT_KEY, "yes");
    } catch {
        // not remembered: the question comes back next time, nothing else changes
    }
}

// The scanned symbol as people write it: "SHOP.TO", "BTC".
export function scanSymbol(trade) {
    return String(trade?.symbol ?? "").trim().toUpperCase();
}

// What to search for: stock search works on the bare ticker and lists every exchange's listing ("SHOP" gives
// SHOP and SHOP.TO), and class shares are written "BRK-B" Yahoo-style but "BRK.B" by the search provider, so
// both suffixes go. Coins are searched by ticker. Searches are capped at 20 characters by the server.
export function scanSearchQuery(trade) {
    const symbol = String(trade?.symbol ?? "").trim();
    const query = trade?.asset_type === "crypto" ? symbol.toLowerCase() : symbol.split(/[.-]/)[0];
    return query.slice(0, 20);
}

// The search result that is the scanned asset, or null. Stocks compare the Yahoo ticker (api_id, e.g. "SHOP.TO",
// which tells the TSX listing from the US one); coins compare the ticker, and the first match is the most popular
// coin with it, the same one the search shows first.
export function pickSearchMatch(results, trade) {
    const want = String(trade?.symbol ?? "").trim().toLowerCase();
    if (!want || !Array.isArray(results)) return null;
    const type = trade.asset_type === "crypto" ? "crypto" : "stock";
    const same = (value) => String(value ?? "").trim().toLowerCase() === want;
    return results.find((result) => result && (!result.type || result.type === type)
        && (type === "stock" ? same(result.api_id) : same(result.symbol) || same(result.api_id))) ?? null;
}

// The server sends naive UTC ("2026-10-30T14:05:00"); without a zone JS would read it as local time
function utcDate(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    let text = value.trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T00:00:00";
    if (!/([zZ]|[+-]\d{2}:?\d{2})$/.test(text)) text += "Z";
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
}

// The scanned date as the form's datetime-local value, in the user's local time, or null when there's none.
// A date with no time on the screenshot keeps its calendar day: today's becomes "now" (it can't be in the future
// then), an earlier one midday, rather than a UTC midnight that would show as the evening before in Canada.
export function scanInputDate(trade, now = new Date()) {
    if (!trade?.date) return null;
    if (trade.date_only) {
        const day = /^\d{4}-\d{2}-\d{2}/.exec(String(trade.date))?.[0];
        if (!day || Number.isNaN(new Date(`${day}T12:00`).getTime())) return null;
        const current = toLocalInputValue(now);
        return current.slice(0, 10) === day ? current : `${day}T12:00`;
    }
    const date = utcDate(trade.date);
    return date ? toLocalInputValue(date) : null;
}

// The add form's starting values from a scanned trade. Only what was read is filled in: a missing quantity or price
// stays empty for the user to type (never 0, never today's market price), a missing date leaves the form's "now".
// The account is "Not set" when the screenshot doesn't say, rather than the last account used in this browser.
export function scanPrefill(trade, now = new Date()) {
    const prefill = {account_type: normalizeAccountType(trade?.account_type) ?? ""};
    if (trade?.action === "BUY" || trade?.action === "SELL") prefill.action = trade.action;
    if (trade?.quantity != null && Number(trade.quantity) > 0) {
        prefill.quantity = quantityInputValue(trade.quantity);
    }
    // the form's price is in the user's currency; the server already converted it at the trade date's rate
    if (trade?.price_in_user_currency != null) {
        const price = priceInputValue(trade.price_in_user_currency);
        if (price) prefill.price_of_one = price;
    }
    const date = scanInputDate(trade, now);
    if (date) prefill.created_at = date;
    return prefill;
}

// The lines shown above the prefilled form: what came from the screenshot, what was converted, what's missing.
export function scanNotes(trade, currency) {
    const notes = ["Filled in from your screenshot. Check every field before saving it."];
    if (trade?.onDevice) notes.push("Read on this device."); // the free reading: the image never left it
    const hasPrice = trade?.price != null && Number(trade.price) > 0;
    const shown = hasPrice ? (trade.currency ? formatPrice(trade.price, trade.currency) : String(trade.price)) : null;

    if (!hasPrice) {
        notes.push("Couldn't read the price. Enter it yourself.");
    } else if (trade.price_in_user_currency == null) {
        notes.push(`The screenshot shows a price of ${shown}, which couldn't be converted. Enter the price in ` +
            `${currency ?? "your currency"}.`);
    } else if (trade.converted && trade.currency) {
        notes.push(`Price converted from ${shown} at ${trade.date ? "that day's" : "today's"} exchange rate.`);
    }
    if (trade?.quantity == null || !(Number(trade.quantity) > 0)) {
        notes.push("Couldn't read the quantity. Enter it yourself.");
    }
    if (!trade?.date) {
        notes.push("No date was found, so it's set to now.");
    } else if (trade.date_only) {
        notes.push("The screenshot only shows the day, so check the time.");
    }
    if (trade?.confidence === "low") notes.push("Confidence: low — double-check the amounts.");

    for (const note of Array.isArray(trade?.notes) ? trade.notes : []) {
        if (typeof note === "string" && note.trim()) notes.push(note.trim());
    }
    return [...new Set(notes)];
}

// "Buy 10 XEQT.TO", "Sell 0.05 BTC": one line of the list shown when a screenshot has several trades.
export function scanTradeLabel(trade) {
    const action = trade?.action === "SELL" ? "Sell" : "Buy";
    const quantity = trade?.quantity != null && Number(trade.quantity) > 0 ? `${formatQuantity(trade.quantity)} ` : "";
    return `${action} ${quantity}${scanSymbol(trade) || "?"}`;
}

// "Oct 30, 2026" for that list, or "" without a date.
export function scanTradeDay(trade, now = new Date()) {
    const value = scanInputDate(trade, now);
    if (!value) return "";
    return new Date(value).toLocaleString(undefined, {month: "short", day: "numeric", year: "numeric"});
}
