// Runs after `vite build --mode ios --outDir dist-ios` (npm run build:ios). Checks the app talks to a real https API,
// then drops files the iOS app never shows, so they aren't shipped inside it. The website's own build (dist/) is
// untouched.
import {readdirSync, readFileSync, rmSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";
import {loadEnv} from "vite";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "dist-ios");

// The API address baked into the app, exactly as Vite resolved it for this build: .env.ios (and any .env.local /
// .env.ios.local), with variables set in the environment (e.g. Codemagic's) taking priority, as in the build.
// A build that would ship a localhost, http or missing address stops here, before `cap sync` copies it into Xcode.
const api = loadEnv("ios", root, "VITE_").VITE_BACKEND_URL ?? "";

function fail(message) {
    console.error(`build:ios stopped: ${message}`);
    process.exit(1);
}

let host = "";
try {
    const url = new URL(api);
    if (url.protocol === "https:") host = url.hostname;
} catch {
    // not a URL at all: reported below
}
if (!host || host === "localhost" || host.endsWith(".localhost") || /^(127\.|\[::1\]$|0\.0\.0\.0$)/.test(host)) {
    fail(`VITE_BACKEND_URL must be the public https API (see frontend/.env.ios), got "${api || "nothing"}"`);
}

// and the bundle really contains it (it would be missing if the build didn't use --mode ios or the variable)
const assets = join(out, "assets");
const bundled = readdirSync(assets)
    .filter((file) => file.endsWith(".js"))
    .some((file) => readFileSync(join(assets, file), "utf8").includes(api));
if (!bundled) {
    fail(`the built JavaScript in dist-ios/assets doesn't contain the API address ${api}`);
}
console.log(`API address in the app: ${api}`);

// the landing page's demo video (8.8 MB): the app skips the landing page
rmSync(join(out, "demo"), {recursive: true, force: true});
// search-engine and link-preview files only matter on the website
for (const file of ["robots.txt", "sitemap.xml", "og-image.png"]) {
    rmSync(join(out, file), {force: true});
}
console.log("Removed website-only files from dist-ios");
