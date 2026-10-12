import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatPercent, formatSignedMoney} from "../utils/format.js";

function TransactionSymbolItem({data, onSub, selected = false}) {
    const {currency} = useUser();

    const select = () => onSub({
        api_id: data.api_id,
        symbol: data.symbol,
        type: data.type,
        price: data.price
    }, data);

    return (
        <div className={`transaction-symbol-item-wrapper${selected ? " selected" : ""}`}>

            <div className="symbol-cell">
                {data.image && <img className="symbol-image" src={data.image} alt=""/>}
                <span className="symbol-text">{data.symbol}</span>
            </div>

            <div className="symbol-price">
                {formatMoney(data.price, currency, {maximumFractionDigits: data.price < 1 ? 6 : 2})}
            </div>

            <div className="symbol-type">
                {data.type}
            </div>

            <div className={`symbol-change ${changeClass(data.change_pct)}`}>
                {formatSignedMoney(data.change, currency)} ({formatPercent(data.change_pct)})
            </div>

            {selected ? (
                <span className="selected-badge">Selected</span>
            ) : (
                <button className="btn btn-primary select-btn" onClick={select}>
                    Select
                </button>
            )}
        </div>
    )
}

export default TransactionSymbolItem
