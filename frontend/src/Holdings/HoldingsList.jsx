import HoldingsItem from "./HoldingsItem.jsx";


function HoldingsList({holdings}) {

    // biggest positions first, ones with no price (null) last
    const value = (h) => h.current_price ?? -Infinity;
    const sorted = [...holdings].sort((a, b) => value(b) - value(a) || 0);

    return (
        <div className="holdings-list-items">
            {sorted.map((t, i) => (
                <HoldingsItem
                    key={`${t.type}-${t.symbol}`}
                    holding={t}
                    index={i}
                />
            ))}
        </div>
    )
}

export default HoldingsList
