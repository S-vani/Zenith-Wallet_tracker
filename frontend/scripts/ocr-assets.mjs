// The on-device text reader (Tesseract.js, src/Transactions/textReader.js) is self-hosted: its worker, its WebAssembly
// core and the English model are copied from node_modules into public/ocr/ whenever Vite starts (dev server, website
// build, `--mode ios` build), so the website and the app serve them themselves. Nothing is fetched from a CDN: a
// screenshot's text stays on the device, and the app can read one offline. public/ocr/ is generated (gitignored).
//
// The library falls back to cdn.jsdelivr.net for any path it isn't given. Every path is given (textReader.js), and
// on top of that those defaults are rewritten to a local path that doesn't exist, in the copied worker and in the
// bundled library, so a missed option fails here instead of quietly downloading from a CDN.
import {existsSync, mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {createRequire} from "node:module";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "ocr");
const CDN = "https://cdn.jsdelivr.net/npm/";
const NO_CDN = "/ocr/no-cdn/";

// node_modules folders, resolved like Node would (tesseract.js-core may sit inside tesseract.js's own node_modules)
function packageDir(name, from = join(root, "package.json")) {
    return dirname(createRequire(from).resolve(`${name}/package.json`));
}

// [source path, file name in public/ocr, rewrite the CDN defaults?]
function sources() {
    const tesseract = packageDir("tesseract.js");
    const core = packageDir("tesseract.js-core", join(tesseract, "package.json"));
    const eng = packageDir("@tesseract.js-data/eng");
    return [
        [join(tesseract, "dist", "worker.min.js"), "worker.min.js", true],
        [join(tesseract, "dist", "worker.min.js.LICENSE.txt"), "worker.min.js.LICENSE.txt", false],
        // LSTM-only cores (the model below has no legacy engine): SIMD where the browser has it, else the plain one.
        // The .wasm.js files carry the WebAssembly inside, so no separate .wasm (or wasm MIME type) is needed.
        [join(core, "tesseract-core-simd-lstm.wasm.js"), "tesseract-core-simd-lstm.wasm.js", false],
        [join(core, "tesseract-core-lstm.wasm.js"), "tesseract-core-lstm.wasm.js", false],
        // "best_int": the integer (fast) LSTM model the library itself uses for LSTM-only, ~3 MB gzipped
        [join(eng, "4.0.0_best_int", "eng.traineddata.gz"), "eng.traineddata.gz", false],
    ];
}

// Copies the files that are missing or changed (a dev restart doesn't rewrite 11 MB each time).
export function copyOcrAssets() {
    mkdirSync(out, {recursive: true});
    for (const [from, name, rewrite] of sources()) {
        let data = readFileSync(from);
        if (rewrite) data = Buffer.from(data.toString("utf8").replaceAll(CDN, NO_CDN), "utf8");
        const to = join(out, name);
        if (existsSync(to) && readFileSync(to).equals(data)) continue;
        writeFileSync(to, data);
    }
}

// Vite plugin: copies the files before anything is served or built, and rewrites the library's CDN defaults in the
// bundled code (the main-thread part; the worker's are rewritten in the copy above).
export default function ocrAssets() {
    return {
        name: "zenith-ocr-assets",
        config() {
            copyOcrAssets();
        },
        // the library reads only its version from its package.json; the rest (its "unpkg"/"jsdelivr" fields,
        // dev dependencies...) would otherwise be bundled for nothing
        load(id) {
            if (!/[\\/]node_modules[\\/]tesseract\.js[\\/]package\.json$/.test(id.split("?")[0])) return null;
            const {version, dependencies} = JSON.parse(readFileSync(id.split("?")[0], "utf8"));
            return JSON.stringify({version, dependencies});
        },
        transform(code, id) {
            if (!/[\\/]node_modules[\\/]tesseract\.js[\\/]/.test(id) || !code.includes(CDN)) return null;
            return {code: code.replaceAll(CDN, NO_CDN), map: null};
        },
    };
}
