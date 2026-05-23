import HoldingsItem from "./HoldingsItem.jsx";


function HoldingsList({holdings}) {

    return (
        <div className="holdings-list-items">
            {holdings.map((t, i) => (
                <HoldingsItem
                    key={t.id}
                    holding={t}
                    style={{animationDelay: `${i * 60}ms`}}
                />
            ))}
        </div>
    )
}

export default HoldingsList
