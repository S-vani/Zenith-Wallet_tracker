import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

// The on-device text reader behind "Scan a screenshot": Apple Vision through the app's plugin, else Tesseract.js.
// Neither can run here (no iPhone, and Tesseract needs a browser's Web Worker and WebAssembly), so both are mocked:
// these tests check which one is used, what it's given and what comes back.

let plugin; // what registerPlugin("TextReader") returns, or null for "no such plugin"
let worker; // the mocked Tesseract worker
let createWorker;

function tesseractPage(lines) {
    return {data: {blocks: [{paragraphs: [{lines}]}]}};
}

const line = (text, x0, y0, x1, y1, confidence = 90) => ({text, bbox: {x0, y0, x1, y1}, confidence});

async function load({native = false} = {}) {
    vi.resetModules();
    vi.doMock("../src/native/platform.js", () => ({isNative: native, loadPlugin: () => () => Promise.resolve({})}));
    vi.doMock("@capacitor/core", () => ({
        registerPlugin: vi.fn((name) => {
            expect(name).toBe("TextReader");
            if (plugin) return plugin;
            // what Capacitor gives for a plugin the app doesn't have
            return {read: () => Promise.reject(Object.assign(new Error("not implemented"), {code: "UNIMPLEMENTED"}))};
        }),
        Capacitor: {isNativePlatform: () => native},
    }));
    vi.doMock("tesseract.js", () => ({createWorker}));
    return import("../src/Transactions/textReader.js");
}

beforeEach(() => {
    plugin = null;
    worker = {
        setParameters: vi.fn(async () => ({})),
        recognize: vi.fn(async () => tesseractPage([
            line("Total cost $312.40", 40, 900, 600, 940),
            line("Shares 10", 40, 800, 300, 840),
            line("~", 10, 10, 20, 20, 3), // an icon read as a letter: dropped
        ])),
        terminate: vi.fn(async () => ({})),
    };
    createWorker = vi.fn(async (langs, oem, options) => {
        options.logger?.({status: "loading tesseract core", progress: 0});
        options.logger?.({status: "recognizing text", progress: 0.5});
        return worker;
    });
});

afterEach(() => {
    vi.doUnmock("../src/native/platform.js");
    vi.doUnmock("@capacitor/core");
    vi.doUnmock("tesseract.js");
    vi.useRealTimers();
});

const image = () => new Blob(["fake jpeg"], {type: "image/jpeg"});

describe("readScreenshotText on the website", () => {
    it("reads with Tesseract from the self-hosted files, never a CDN", async () => {
        const {readScreenshotText} = await load();
        const result = await readScreenshotText(image());

        expect(result.engine).toBe("tesseract");
        expect(createWorker).toHaveBeenCalledTimes(1);
        const [langs, oem, options] = createWorker.mock.calls[0];
        expect(langs).toBe("eng");
        expect(oem).toBe(1); // LSTM only: the shipped core and model have no legacy engine
        expect(options.workerPath).toMatch(/\/ocr\/worker\.min\.js$/);
        expect(options.corePath).toMatch(/\/ocr\/$/);
        expect(options.langPath).toMatch(/\/ocr\/$/);
        expect(options.workerBlobURL).toBe(false);
        expect(JSON.stringify(options)).not.toMatch(/jsdelivr|unpkg|cdn/i);
        expect(worker.recognize).toHaveBeenCalledWith(expect.anything(), {}, {blocks: true, text: false});
    });

    it("gives the lines top to bottom as fractions of the page, without the noise", async () => {
        const {readScreenshotText} = await load();
        const {lines} = await readScreenshotText(image());
        // no canvas here, so the furthest text (x 600, y 940) sets the scale
        expect(lines.map((l) => l.text)).toEqual(["Shares 10", "Total cost $312.40"]);
        expect(lines[0]).toEqual({text: "Shares 10", x: 40 / 600, y: 800 / 940, w: 260 / 600, h: 40 / 940});
    });

    it("never asks for the app's plugin", async () => {
        const {readScreenshotText} = await load();
        await readScreenshotText(image());
        const {registerPlugin} = await import("@capacitor/core");
        expect(registerPlugin).not.toHaveBeenCalled();
    });

    it("says when it's getting ready and how far the reading is", async () => {
        const {readScreenshotText} = await load();
        const seen = [];
        await readScreenshotText(image(), {onProgress: (p) => seen.push(p)});
        expect(seen).toContainEqual({phase: "loading", progress: null});
        expect(seen).toContainEqual({phase: "reading", progress: 0.5});

        // the second scan reuses the worker: no "getting ready" this time
        const again = [];
        await readScreenshotText(image(), {onProgress: (p) => again.push(p)});
        expect(createWorker).toHaveBeenCalledTimes(1);
        expect(again[0]).toEqual({phase: "reading", progress: null});
    });

    it("closes the worker after a minute without a scan", async () => {
        vi.useFakeTimers();
        const {readScreenshotText} = await load();
        await readScreenshotText(image());
        await vi.advanceTimersByTimeAsync(59_000);
        expect(worker.terminate).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(2_000);
        expect(worker.terminate).toHaveBeenCalledTimes(1);

        await readScreenshotText(image()); // and starts a new one when needed
        expect(createWorker).toHaveBeenCalledTimes(2);
    });

    it("stops reading when the scan is cancelled", async () => {
        const {readScreenshotText} = await load();
        let finish;
        worker.recognize = vi.fn(() => new Promise((resolve) => {
            finish = resolve;
        }));
        const controller = new AbortController();
        const reading = readScreenshotText(image(), {signal: controller.signal});
        await vi.waitFor(() => expect(worker.recognize).toHaveBeenCalled());
        controller.abort();
        await expect(reading).rejects.toMatchObject({name: "AbortError"});
        await vi.waitFor(() => expect(worker.terminate).toHaveBeenCalled());
        finish(tesseractPage([])); // a late answer changes nothing
    });

    it("rejects at once for a scan cancelled before it starts", async () => {
        const {readScreenshotText} = await load();
        const controller = new AbortController();
        controller.abort();
        await expect(readScreenshotText(image(), {signal: controller.signal})).rejects.toMatchObject({name: "AbortError"});
        expect(createWorker).not.toHaveBeenCalled();
    });

    it("turns Tesseract's own errors into a readable message, and tries again next time", async () => {
        const {readScreenshotText} = await load();
        createWorker.mockRejectedValueOnce("Network error while fetching /ocr/eng.traineddata.gz. Response code: 404");
        await expect(readScreenshotText(image())).rejects.toThrow("Couldn't read the text on this screenshot.");
        await expect(readScreenshotText(image())).resolves.toMatchObject({engine: "tesseract"});
    });
});

describe("readScreenshotText in the iPhone app", () => {
    it("reads with Apple Vision, sending the image as plain base64", async () => {
        plugin = {
            read: vi.fn(async () => ({
                lines: [
                    {text: "Total cost   $312.40", x: 0.05, y: 0.5, w: 0.8, h: 0.03},
                    {text: "Shares", x: 0.05, y: 0.4, w: 0.2, h: 0.03},
                    {text: "10", x: 0.85, y: 0.401, w: 0.05, h: 0.03},
                    {text: "  ", x: 0.1, y: 0.1, w: 0.1, h: 0.1}, // empty: dropped
                    {text: "bad", x: "?", y: 0.2}, // malformed: dropped
                    {text: "edge", x: -0.01, y: 0.9, w: 1.2, h: 0.05}, // clamped to the image
                ],
            })),
        };
        const {readScreenshotText} = await load({native: true});
        const result = await readScreenshotText(image());

        expect(result.engine).toBe("vision");
        expect(plugin.read).toHaveBeenCalledWith({image: btoa("fake jpeg")});
        expect(result.lines.map((l) => l.text)).toEqual(["Shares", "10", "Total cost   $312.40", "edge"]);
        expect(result.lines.at(-1)).toMatchObject({x: 0, w: 1});
        expect(createWorker).not.toHaveBeenCalled(); // Tesseract isn't even loaded
    });

    it("falls back to Tesseract when the app has no plugin (an older build)", async () => {
        const {readScreenshotText} = await load({native: true});
        await expect(readScreenshotText(image())).resolves.toMatchObject({engine: "tesseract"});
    });

    it("falls back to Tesseract when Vision fails", async () => {
        plugin = {read: vi.fn(async () => Promise.reject(new Error("The text on this screenshot couldn't be read.")))};
        const {readScreenshotText} = await load({native: true});
        await expect(readScreenshotText(image())).resolves.toMatchObject({engine: "tesseract"});
        expect(plugin.read).toHaveBeenCalled();
        // and the app's Tesseract doesn't keep a second copy of the model it already has in its bundle
        expect(createWorker.mock.calls[0][2].cacheMethod).toBe("none");
    });

    it("keeps an empty answer from Vision (nothing on the screenshot) rather than reading again", async () => {
        plugin = {read: vi.fn(async () => ({lines: []}))};
        const {readScreenshotText} = await load({native: true});
        await expect(readScreenshotText(image())).resolves.toEqual({lines: [], engine: "vision"});
        expect(createWorker).not.toHaveBeenCalled();
    });

    it("lets a cancelled scan go without waiting for Vision", async () => {
        plugin = {read: vi.fn(() => new Promise(() => {}))};
        const {readScreenshotText} = await load({native: true});
        const controller = new AbortController();
        const reading = readScreenshotText(image(), {signal: controller.signal});
        await vi.waitFor(() => expect(plugin.read).toHaveBeenCalled());
        controller.abort();
        await expect(reading).rejects.toMatchObject({name: "AbortError"});
        expect(createWorker).not.toHaveBeenCalled();
    });
});

describe("tesseractLines / orderLines", () => {
    it("scales boxes by the image's size when it's known", async () => {
        const {tesseractLines} = await load();
        const lines = tesseractLines({blocks: [{paragraphs: [{lines: [line("Price $31.24", 100, 200, 500, 240)]}]}]},
            1000, 2000);
        expect(lines).toEqual([{text: "Price $31.24", x: 0.1, y: 0.1, w: 0.4, h: 0.02}]);
        expect(tesseractLines(null)).toEqual([]);
        expect(tesseractLines({blocks: [{paragraphs: [{lines: [{text: "no box"}]}]}]})).toEqual([]);
    });

    it("puts lines of one row left to right, rows top to bottom", async () => {
        const {orderLines} = await load();
        const rows = orderLines([
            {text: "b", x: 0.6, y: 0.2, w: 0.1, h: 0.04},
            {text: "c", x: 0.1, y: 0.3, w: 0.1, h: 0.04},
            {text: "a", x: 0.1, y: 0.205, w: 0.1, h: 0.04},
        ]);
        expect(rows.map((l) => l.text)).toEqual(["a", "b", "c"]);
    });
});
