// "Scan a screenshot", step 1: the text on the screenshot, read on this device. Free, works offline in the app, and
// the image never leaves the device (step 2, tradeTextParser.js, turns the text into trade fields, and only those
// go to the server).
//   - iPhone app: Apple Vision, through the app's own TextReader plugin (ios/App/App/TextReaderPlugin.swift).
//   - Website (and the app if the plugin is missing or fails): Tesseract.js, self-hosted under /ocr/ (copied from
//     node_modules by scripts/ocr-assets.mjs; never a CDN), loaded only when a scan starts. One worker, closed after
//     a minute without a scan so its ~20 MB of memory goes back.
// Both give lines top to bottom with coordinates as fractions of the image (0..1, top left origin).
import {registerPlugin} from "@capacitor/core";
import {isNative} from "../native/platform.js";

const IDLE_MS = 60_000;
const OEM_LSTM_ONLY = 1; // Tesseract's neural engine only: the model and core shipped in /ocr/ have nothing else
const PSM_SPARSE_TEXT = "11";
const MIN_CONFIDENCE = 10; // below this a "line" is an icon or a smudge read as letters

let nativeReader = null; // the app's plugin, registered on first use (never on the website)
let workerPromise = null;
let idleTimer = null;
let reading = 0; // scans in progress, so the idle timer never closes the worker under one
let progressListener = null;

// {lines: [{text, x, y, w, h}], engine: "vision" | "tesseract"} for an image Blob. `onProgress({phase, progress})`
// hears "loading" (Tesseract getting ready, the first time a few MB are downloaded) and "reading" (progress 0..1
// when known, else null). `signal` cancels: the promise rejects with an AbortError and Tesseract stops.
export async function readScreenshotText(blob, {signal, onProgress} = {}) {
    throwIfAborted(signal);
    if (isNative) {
        const lines = await readWithVision(blob, signal);
        if (lines) return {lines, engine: "vision"};
    }
    try {
        return {lines: await readWithTesseract(blob, {signal, onProgress}), engine: "tesseract"};
    } catch (err) {
        if (err?.name === "AbortError" || signal?.aborted) throw err?.name === "AbortError" ? err : abortError();
        // Tesseract rejects with plain strings ("Network error while fetching..."): never shown as they are
        throw new Error(globalThis.navigator?.onLine === false
            ? "The text reader needs a connection the first time. Connect and try again, or enter the trade yourself."
            : "Couldn't read the text on this screenshot. Please try again, or enter the trade yourself.",
        {cause: err});
    }
}

// Closes the Tesseract worker now (cancelling a scan, or nothing to read for a while). Safe to call anytime.
export function closeTextReader() {
    clearTimeout(idleTimer);
    idleTimer = null;
    const worker = workerPromise;
    workerPromise = null;
    worker?.then((w) => w.terminate()).catch(() => {});
}

// ---------------------------------------------------------------------------------------------------------------------
// Apple Vision (iPhone app)
// ---------------------------------------------------------------------------------------------------------------------

// The lines from the app's plugin, or null when it can't read (an older app build without the plugin, an image it
// can't open...), so Tesseract tries instead. A cancelled scan rejects with an AbortError.
async function readWithVision(blob, signal) {
    let result;
    try {
        nativeReader ??= registerPlugin("TextReader");
        const image = await toBase64(blob);
        throwIfAborted(signal);
        result = await untilAborted(nativeReader.read({image}), signal);
    } catch (err) {
        if (err?.name === "AbortError") throw err;
        return null; // "UNIMPLEMENTED" or the plugin's own error
    }
    return Array.isArray(result?.lines) ? orderLines(result.lines.map(cleanLine).filter(Boolean)) : null;
}

// The image as base64, without the "data:...;base64," prefix the plugin doesn't want
async function toBase64(blob) {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
}

// ---------------------------------------------------------------------------------------------------------------------
// Tesseract.js (website, and the app's fallback)
// ---------------------------------------------------------------------------------------------------------------------

// The self-hosted files' folder as an absolute URL: the worker loads them by URL from its own scope
function ocrBase() {
    const base = `${import.meta.env.BASE_URL ?? "/"}ocr/`;
    return new URL(base, globalThis.location?.href ?? "http://localhost/").href;
}

// The one worker, started on first use. Every path is given, so nothing is ever fetched from a CDN.
function getWorker() {
    if (!workerPromise) {
        const starting = (async () => {
            const tesseract = await import("tesseract.js");
            const createWorker = tesseract.createWorker ?? tesseract.default?.createWorker;
            const base = ocrBase();
            const worker = await createWorker("eng", OEM_LSTM_ONLY, {
                workerPath: `${base}worker.min.js`,
                corePath: base, // a folder: the worker picks the SIMD build when the browser has SIMD
                langPath: base,
                gzip: true,
                workerBlobURL: false, // same origin, so the worker script loads directly
                // the website keeps the model in IndexedDB after the first download; the app has it in its bundle
                cacheMethod: isNative ? "none" : "write",
                logger: (message) => progressListener?.(message),
            });
            // "Sparse text": a UI screenshot is bits of text all over the screen, not a page of paragraphs. The
            // library's default (one uniform block) drops lone headings such as the ticker at the top of an order
            // screen. Labels and values come out as separate lines with their boxes, and the parser puts them
            // back together by row.
            await worker.setParameters({tessedit_pageseg_mode: PSM_SPARSE_TEXT});
            return worker;
        })();
        workerPromise = starting;
        // a failed start (offline before the first download, a blocked worker) is tried again next time
        starting.catch(() => {
            if (workerPromise === starting) workerPromise = null;
        });
    }
    return workerPromise;
}

async function readWithTesseract(blob, {signal, onProgress}) {
    reading += 1;
    clearTimeout(idleTimer);
    idleTimer = null;
    const onAbort = () => closeTextReader(); // stops the recognition in the middle; the next scan starts a new one
    signal?.addEventListener("abort", onAbort, {once: true});
    progressListener = (message) => {
        const status = String(message?.status ?? "");
        const recognizing = status.startsWith("recognizing");
        const progress = Number(message?.progress);
        onProgress?.({
            phase: recognizing ? "reading" : "loading",
            progress: recognizing && Number.isFinite(progress) ? Math.min(1, Math.max(0, progress)) : null,
        });
    };
    try {
        if (!workerPromise) onProgress?.({phase: "loading", progress: null});
        const worker = await untilAborted(getWorker(), signal);
        onProgress?.({phase: "reading", progress: null});
        const image = await prepareImage(blob);
        throwIfAborted(signal);
        const result = await untilAborted(worker.recognize(image.source, {}, {blocks: true, text: false}), signal);
        return tesseractLines(result?.data, image.width, image.height);
    } finally {
        signal?.removeEventListener("abort", onAbort);
        progressListener = null;
        reading -= 1;
        if (reading === 0 && workerPromise) idleTimer = setTimeout(closeTextReader, IDLE_MS);
    }
}

// Tesseract reads dark text on a light background best: a dark-mode screenshot (light text on black) is turned
// around, in grey. Only a really small image is drawn bigger: tiny letters are where it misreads most, but blowing
// up a phone screenshot makes its big headings (the ticker on an order screen) too large for it to see as text.
// Without a canvas (or if drawing fails) the image goes as it is.
async function prepareImage(blob) {
    try {
        if (typeof document === "undefined" || typeof createImageBitmap !== "function") throw new Error("no canvas");
        const bitmap = await createImageBitmap(blob);
        const scale = Math.max(bitmap.width, bitmap.height) < 700 ? 2 : 1;
        const width = bitmap.width * scale;
        const height = bitmap.height * scale;
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d", {willReadFrequently: true});
        ctx.drawImage(bitmap, 0, 0, width, height);
        bitmap.close?.();
        const pixels = ctx.getImageData(0, 0, width, height);
        const data = pixels.data;
        let sum = 0;
        for (let i = 0; i < data.length; i += 4) {
            const grey = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            data[i] = data[i + 1] = data[i + 2] = grey;
            sum += grey;
        }
        if (sum / (data.length / 4) < 110) {
            for (let i = 0; i < data.length; i += 4) data[i] = data[i + 1] = data[i + 2] = 255 - data[i];
        }
        ctx.putImageData(pixels, 0, 0);
        return {source: canvas, width, height};
    } catch {
        return {source: blob, width: 0, height: 0};
    }
}

// Tesseract's blocks → paragraphs → lines as {text, x, y, w, h} fractions of the image. Without the image's size,
// the furthest text decides the scale (only the layout matters to the parser, not exact positions).
export function tesseractLines(data, width = 0, height = 0) {
    const raw = [];
    for (const block of Array.isArray(data?.blocks) ? data.blocks : []) {
        for (const paragraph of block?.paragraphs ?? []) {
            for (const line of paragraph?.lines ?? []) {
                const text = String(line?.text ?? "").replace(/\s+/g, " ").trim();
                const box = line?.bbox;
                if (!text || !box || !(Number(line.confidence ?? 100) >= MIN_CONFIDENCE)) continue;
                raw.push({text, x0: box.x0, y0: box.y0, x1: box.x1, y1: box.y1});
            }
        }
    }
    const w = width || Math.max(1, ...raw.map((l) => l.x1));
    const h = height || Math.max(1, ...raw.map((l) => l.y1));
    return orderLines(raw.map((l) => cleanLine({
        text: l.text, x: l.x0 / w, y: l.y0 / h, w: (l.x1 - l.x0) / w, h: (l.y1 - l.y0) / h,
    })).filter(Boolean));
}

// ---------------------------------------------------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------------------------------------------------

const clamp = (n) => Math.min(1, Math.max(0, n));

// One line as the parser takes it, or null for an empty or malformed one
function cleanLine(line) {
    const text = typeof line?.text === "string" ? line.text.trim() : "";
    const numbers = ["x", "y", "w", "h"].map((k) => Number(line?.[k]));
    if (!text || !numbers.every(Number.isFinite)) return null;
    const [x, y, w, h] = numbers.map(clamp);
    return {text, x, y, w, h};
}

// Top to bottom; lines on the same row (middles within half a line) left to right, like the app's plugin
export function orderLines(lines) {
    const byMiddle = [...lines].sort((a, b) => (a.y + a.h / 2) - (b.y + b.h / 2));
    const rows = [];
    for (const line of byMiddle) {
        const row = rows.at(-1);
        const first = row?.[0];
        if (first && Math.abs((first.y + first.h / 2) - (line.y + line.h / 2)) < Math.min(first.h, line.h) / 2) {
            row.push(line);
        } else {
            rows.push([line]);
        }
    }
    return rows.flatMap((row) => row.sort((a, b) => a.x - b.x));
}

function abortError() {
    return new DOMException("The scan was cancelled.", "AbortError");
}

function throwIfAborted(signal) {
    if (signal?.aborted) throw abortError();
}

// The promise, or an AbortError as soon as the signal fires (the work itself may go on: its result is ignored)
function untilAborted(promise, signal) {
    if (!signal) return promise;
    throwIfAborted(signal);
    return new Promise((resolve, reject) => {
        const onAbort = () => reject(abortError());
        signal.addEventListener("abort", onAbort, {once: true});
        promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
    });
}
