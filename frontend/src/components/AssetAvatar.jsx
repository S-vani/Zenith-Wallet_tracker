// A round badge for a stock or coin: the coin's own colour for the best known ones, otherwise a colour worked out from
// the symbol (so AAPL always looks the same) with its first letters. Real logos would need a paid logo service for
// stocks; search results that come with a CoinGecko image show that instead (SearchResults.jsx). Decorative only:
// the symbol is always written next to it.
const KNOWN = {
    btc: "#f7931a", eth: "#627eea", sol: "#9945ff", usdt: "#26a17b", usdc: "#2775ca", xrp: "#23292f",
    doge: "#c2a633", ada: "#0033ad", bnb: "#f3ba2f", ltc: "#345d9d", dot: "#e6007a", avax: "#e84142",
};

// A stable hue (0-359) for a symbol, so the same stock always gets the same colour.
function hue(text) {
    let h = 0;
    for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return h;
}

// The badge; `size` is "md" (lists) or "sm" (inline next to a symbol).
function AssetAvatar({symbol = "", type = "stock", size = "md"}) {
    const base = String(symbol).split(/[.\-:]/)[0].toUpperCase();
    const known = type === "crypto" ? KNOWN[base.toLowerCase()] : null;
    const h = hue(base || "?");
    const style = known
        ? {background: known, color: "#fff"}
        : {background: `hsl(${h} 45% 24%)`, color: `hsl(${h} 85% 82%)`, boxShadow: `inset 0 0 0 1px hsl(${h} 50% 34%)`};
    return (
        <span className={`asset-avatar ${size}${type === "crypto" ? " crypto" : ""}`} style={style} aria-hidden="true">
            {base.slice(0, 2) || "?"}
        </span>
    );
}

export default AssetAvatar;
