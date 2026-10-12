import HoldingsItem from "./HoldingsItem.jsx";


function HoldingsList({holdings}) {

    // biggest positions first
    const sorted = [...holdings].sort((a, b) => b.current_price - a.current_price);

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
