// Contrast gate: reads the colour tokens of every theme (src/design/tokens.css + themes.css) and checks the text and
// accent pairs against WCAG AA. Run: node scripts/check-contrast.mjs  (exits 1 when a pair fails). A palette change
// is only done when this passes.
import {readFileSync} from "node:fs";

const read = (f) => readFileSync(new URL(`../src/design/${f}`, import.meta.url), "utf8");
const tokensCss = read("tokens.css");
const themesCss = read("themes.css");

// "--name: #abc123;" and "--name: rgb(r g b / a);" declarations inside a block
function declarations(block) {
    const out = {};
    for (const m of block.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
    return out;
}
const rootBlock = tokensCss.slice(tokensCss.indexOf(":root {"), tokensCss.indexOf("/* the names the older CSS"));
const midnight = declarations(rootBlock);
const themeBlock = (name) => {
    const start = themesCss.indexOf(`:root[data-theme="${name}"]`);
    return declarations(themesCss.slice(start, themesCss.indexOf("\n}\n", start)));
};
const themes = {midnight, black: {...midnight, ...themeBlock("black")}, daylight: {...midnight, ...themeBlock("daylight")}};

function parse(value) { // #rrggbb, or rgb(r g b / a) (composited over `over`)
    if (value.startsWith("#")) {
        const h = value.slice(1);
        const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
        return {rgb: [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)), a: 1};
    }
    const m = value.match(/rgb\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\s*\)/);
    return m ? {rgb: [+m[1], +m[2], +m[3]], a: m[4] === undefined ? 1 : +m[4]} : null;
}
const flat = (colour, over) => parse(colour).rgb.map((c, i) => c * parse(colour).a + over[i] * (1 - parse(colour).a));
const lum = ([r, g, b]) => {
    const f = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const ratio = (a, b) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
};

// [foreground token (or #fff), background token(s), minimum ratio, why]
const PAIRS = [
    ["text", ["bg", "surface", "surface-2", "surface-3"], 7, "body text"],
    ["text-soft", ["bg", "surface", "surface-2"], 4.5, "secondary text"],
    ["text-muted", ["bg", "surface", "surface-2", "surface-3"], 4.5, "muted text"],
    ["text-subtle", ["bg", "surface", "surface-2"], 4.5, "subtle text"],
    ["placeholder", ["surface-sunken", "surface"], 3, "placeholders"],
    ["accent-text", ["bg", "surface", "surface-2", "accent-fill"], 4.5, "links and active text"],
    ["positive", ["bg", "surface", "surface-2"], 4.5, "gains as text"],
    ["negative", ["bg", "surface", "surface-2"], 4.5, "losses as text"],
    ["negative-text", ["bg", "surface"], 4.5, "error text"],
    ["warn-text", ["bg", "surface"], 4.5, "warning text"],
    ["positive-text", ["bg", "surface"], 4.5, "success text"],
    ["#ffffff", ["accent-deep"], 4.5, "white on the primary button's dark end"],
    ["#ffffff", ["accent"], 3, "white on the primary button's light end (bold, large UI text)"],
];

let failed = 0;
for (const [name, tokens] of Object.entries(themes)) {
    for (const [fg, bgs, min, why] of PAIRS) {
        for (const bgName of bgs) {
            const base = flat(tokens.bg, [0, 0, 0]);
            const back = flat(tokens[bgName], base);
            const front = fg.startsWith("#") ? parse(fg).rgb : flat(tokens[fg], back);
            const r = ratio(front, back);
            if (r < min) {
                failed++;
                console.log(`FAIL ${name}: ${fg} on ${bgName} = ${r.toFixed(2)} (needs ${min}) ${why}`);
            }
        }
    }
}
console.log(failed ? `${failed} contrast pair(s) below the minimum` : "all contrast pairs pass in midnight, black and daylight");
process.exit(failed ? 1 : 0);
