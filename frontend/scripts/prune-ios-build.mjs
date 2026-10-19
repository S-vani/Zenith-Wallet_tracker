// Runs after `vite build --outDir dist-ios` (npm run build:ios). Drops files the iOS app never shows,
// so they aren't shipped inside it. The website's own build (dist/) is untouched.
import {rmSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const out = join(dirname(fileURLToPath(import.meta.url)), "..", "dist-ios");

// the landing page's demo video (8.8 MB): the app skips the landing page
rmSync(join(out, "demo"), {recursive: true, force: true});
// search-engine and link-preview files only matter on the website
for (const file of ["robots.txt", "sitemap.xml", "og-image.png"]) {
    rmSync(join(out, file), {force: true});
}
console.log("Removed website-only files from dist-ios");
