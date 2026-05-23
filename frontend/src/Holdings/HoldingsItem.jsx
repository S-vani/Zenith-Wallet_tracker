import HoldingsChart from "./HoldingsChart.jsx"
import {useState} from "react";

function HoldingsItem({holding}) {
    const [expanded, setExpanded] = useState(false);
    const [isOpen, setIsOpen] = useState(false)

    const onclick = () => {
        setIsOpen(!isOpen);
        setExpanded(!expanded)
    }

    const data = {
        "symbol": holding.symbol,
        "type": holding.type,
        "current_total_price": holding.current_price.toFixed(2),
        "quantity": holding.quantity,
        "return": (holding.current_price - holding.price_paid).toFixed(2),
        "return_pct": (100 * ((holding.current_price - holding.price_paid)/holding.price_paid)).toFixed(2)
    }

    let classReturn = "change-pct"
    if (data.return_pct > 0){
        classReturn += " positive"
    }
    else{
        classReturn += " negative"
    }

    return (
        <div className="holding-item-wrapper">
            <div className="holding-item" onClick={onclick}>
                <div className="position-column">
                    <p>{data.symbol}</p>
                    <p>{data.type}</p>
                </div>

                <span>$ {data.current_total_price} CAD</span>
                <span className="quantity-item">{data.quantity} </span>
                <span className={classReturn}>$ {data.return} CAD</span>
                <span className={classReturn}>{data.return_pct}%</span>

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
