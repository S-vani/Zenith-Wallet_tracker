import HoldingsChart from "./HoldingsChart.jsx"
import {useState} from "react";

function HoldingsItem({holding}) {
    const [expanded, setExpanded] = useState(false);
    const [isOpen, setIsOpen] = useState(false)

    const onclick = () => {
        setIsOpen(!isOpen);
        setExpanded(!expanded)
    }

    return (
        <div className="holding-item-wrapper">
            <div onClick={onclick}>
                <span>{holding.symbol}</span>
                <span>{holding.current_price}</span>
                <span>{holding.current_price - holding.price_paid}</span>
                <span>{holding.quantity}</span>
                <span>{holding.type}</span>
                <span className="expand-icon">
                    {expanded ? "▲" : "▼"}
                </span>
            </div>

            {isOpen && (
                <div>
                    <HoldingsChart symbol={holding.symbol} type={holding.type}/>
                </div>
            )}
        </div>
    )
}

export default HoldingsItem
