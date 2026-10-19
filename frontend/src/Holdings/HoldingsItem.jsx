import HoldingsChart from "./HoldingsChart.jsx"
import {useState} from "react";
import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatPercent, formatQuantity, formatSignedMoney} from "../utils/format.js";

function HoldingsItem({holding, index}) {
    const [isOpen, setIsOpen] = useState(false)
    const {currency} = useUser();

    // null current_price = no source has a price for it: show "—" instead of $0 / −100%
    const priced = holding.current_price !== null && holding.current_price !== undefined;
    const gain = priced ? holding.current_price - holding.price_paid : null;
    const gainPct = priced && holding.price_paid > 0 ? (gain / holding.price_paid) * 100 : null;
    const classReturn = `change-pct ${changeClass(gain)}`;

    return (
        <div className={`holding-item-wrapper${isOpen ? " open" : ""}`} style={{animationDelay: `${index * 60}ms`}}>
            <button className="holding-item" onClick={() => setIsOpen(!isOpen)} aria-expanded={isOpen}>
                <div className="position-column">
                    <span className="position-symbol">{holding.symbol}</span>
                    <span className="position-type">{holding.type}</span>
                </div>

                <span className="holding-cell" data-label="Value"
                      title={priced ? undefined : "Price unavailable"}>{priced ? formatMoney(holding.current_price, currency) : "—"}</span>
                <span className="holding-cell" data-label="Quantity">{formatQuantity(holding.quantity)}</span>
                <span className={`holding-cell ${classReturn}`} data-label="Return">{priced ? formatSignedMoney(gain, currency) : "—"}</span>
                <span className={`holding-cell ${classReturn}`} data-label="Return %">{priced ? formatPercent(gainPct) : "—"}</span>

                <span className="expand-icon" aria-hidden="true">▾</span>
            </button>

            {isOpen && (
                <div className="holding-chart-panel">
                    <HoldingsChart symbol={holding.symbol} type={holding.type}/>
                </div>
            )}
        </div>
    )
}

export default HoldingsItem
