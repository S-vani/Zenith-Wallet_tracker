"""
One-off migration used to move the CSS from hard-coded colours to the design tokens (src/design/tokens.css).
Kept in the repo as a record of the mapping. Run from frontend/:  python scripts/migrate-colours.py [--dry]

It rewrites hex colours and rgba() literals in src/css/*.css using the CSS property on the same line to decide what a
translucent white means (a border or a fill), and prints what it could not map so that can be done by hand.
"""
import re
import sys
from pathlib import Path

DRY = "--dry" in sys.argv
CSS = Path(__file__).resolve().parent.parent / "src" / "css"

HEX = {
    # text
    "f5f7ff": "var(--text)", "f3f6fc": "var(--text)",
    "9aa0a6": "var(--text-muted)",
    "8b93a1": "var(--text-subtle)", "94a3b8": "var(--text-subtle)", "94a3c4": "var(--text-subtle)",
    "6b7280": "var(--text-subtle)", "6b7790": "var(--text-subtle)",
    "5a6785": "var(--placeholder)",
    "c7d2e6": "var(--text-soft)", "c7d2e8": "var(--text-soft)", "cbd5e1": "var(--text-soft)", "d1d5db": "var(--text-soft)",
    "93c5fd": "var(--accent-text)", "60a5fa": "var(--accent-text)",
    "fca5a5": "var(--negative-text)", "f87171": "var(--negative-text)",
    "fcd34d": "var(--warn-text)", "fbbf24": "var(--warn-text)", "fde68a": "var(--warn-text)",
    "f59e0b": "var(--warn)", "facc15": "var(--gold)", "c4b5fd": "var(--violet-text)",
    "86efac": "var(--positive-text)", "4ade80": "var(--positive-text)",
    # semantic hues
    "22c55e": "var(--positive)", "ef4444": "var(--negative)",
    "3b82f6": "var(--accent)", "2563eb": "var(--accent-deep)", "1d4ed8": "var(--accent-deep)",
    # surfaces
    "0b1220": "var(--surface)", "0d1322": "var(--surface)", "0d1526": "var(--surface)", "0f1725": "var(--surface)",
    "141a28": "var(--surface)", "161b28": "var(--surface)", "131722": "var(--surface)",
    "121a2b": "var(--surface-2)", "111a2d": "var(--surface-2)", "1c2335": "var(--surface-2)", "1e2433": "var(--surface-2)",
    "2b3446": "var(--surface-3)",
    "070b14": "var(--surface-sunken)", "05070d": "var(--surface-sunken)", "080c15": "var(--surface-sunken)",
    "0d1017": "var(--surface-sunken)", "050e1c": "var(--surface-sunken)",
    "060a12": "var(--bg)", "070b12": "var(--bg)", "050912": "var(--bg)",
    "07101f": "var(--glow-1)", "0f1f45": "var(--glow-2)", "13254a": "var(--glow-2)",
    # blue fills and lines
    "1d3461": "var(--accent-fill)", "162344": "var(--accent-fill-2)",
    "2f4a7a": "var(--accent-line)", "3b5b94": "var(--accent-line)",
    "22355a": "var(--line-strong)", "2a3d60": "var(--line-strong)", "1b2a44": "var(--line-strong)",
    "13213a": "var(--line)",
}
HEX8 = {"2f4a7a44": "rgb(var(--accent-rgb) / 0.27)", "2f4a7a33": "rgb(var(--accent-rgb) / 0.2)"}
KEEP_HEX = {"fff", "ffffff", "000", "000000", "000000cc", "1c1c1e", "151517", "0c0c0e", "0a84ff", "8e8e93", "ff453a",
            "1f1300", "b91c1c", "dc2626", "166534", "15803d", "16a34a", "0b1424"}

TINTS = {  # rgb triple -> replacement template with {a}
    (59, 130, 246): "rgb(var(--accent-rgb) / {a})", (96, 165, 250): "rgb(var(--accent-rgb) / {a})",
    (34, 197, 94): "rgb(var(--positive-rgb) / {a})",
    (239, 68, 68): "rgb(var(--negative-rgb) / {a})", (248, 113, 113): "rgb(var(--negative-rgb) / {a})",
    (245, 158, 11): "rgb(var(--warn-rgb) / {a})",
    (6, 10, 18): "rgb(var(--bg-rgb) / {a})", (8, 12, 22): "rgb(var(--bg-rgb) / {a})",
    (30, 36, 51): "rgb(var(--surface-2-rgb) / {a})", (22, 27, 40): "rgb(var(--surface-rgb) / {a})",
}
RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)")
HEXRE = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def bucket(alpha, names):
    return names[0] if alpha <= 0.055 else names[1] if alpha <= 0.095 else names[2]


def fix_rgba(m, line):
    r, g, b, a = int(m[1]), int(m[2]), int(m[3]), float(m[4])
    if (r, g, b) in TINTS:
        return TINTS[(r, g, b)].format(a=m[4])
    if (r, g, b) == (148, 163, 196):
        return "var(--line)"
    if (r, g, b) == (255, 255, 255):
        stripped = line.strip()
        if re.match(r"(border|outline)[a-z-]*\s*:", stripped):
            return f"var({bucket(a, ('--line-faint', '--line', '--line-strong'))})"
        if re.match(r"background[a-z-]*\s*:", stripped) and "gradient" not in stripped:
            return f"var({bucket(a, ('--fill-faint', '--fill', '--fill-strong'))})"
        if "inset" in stripped and a <= 0.09:
            return "var(--edge-light)"
        return m[0]
    if (r, g, b) == (0, 0, 0):
        stripped = line.strip()
        if re.match(r"(box-shadow|filter|text-shadow)\s*:", stripped) or "drop-shadow" in stripped:
            return f"rgb(var(--shadow-rgb) / {m[4]})"
        if re.match(r"background[a-z-]*\s*:", stripped) and a <= 0.3 and "gradient" not in stripped:
            return "var(--sunken)"
        return m[0]
    return m[0]


def fix_hex(m):
    h = m[1].lower()
    if len(h) == 8:
        return HEX8.get(h, m[0])
    if h in KEEP_HEX:
        return m[0]
    return HEX.get(h, m[0])


changed = 0
left = {}
for path in sorted(CSS.glob("*.css")):
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(keepends=True), 1):
        new = RGBA.sub(lambda m: fix_rgba(m, line), line)
        new = HEXRE.sub(fix_hex, new)
        if new != line:
            changed += 1
        out.append(new)
        for tok in HEXRE.findall(new):
            if tok.lower() not in KEEP_HEX:
                left.setdefault(path.name, []).append((lineno, "#" + tok))
    if not DRY:
        path.write_text("".join(out), encoding="utf-8", newline="")
print(f"{changed} lines changed{' (dry run)' if DRY else ''}")
for name, items in left.items():
    print(name, items[:12])
