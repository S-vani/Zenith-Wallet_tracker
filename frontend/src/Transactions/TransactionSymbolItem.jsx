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

    const price = formatMoney(data.price, currency, {maximumFractionDigits: data.price < 1 ? 6 : 2});
    const change = formatSignedMoney(data.change, currency);
    const changePct = formatPercent(data.change_pct);

    return (
        <div className={`transaction-symbol-item-wrapper${selected ? " selected" : ""}`}>
            <div className="symbol-card-grid">

                <div className="symbol-cell">
                    {data.image && <img className="symbol-image" src={data.image} alt=""/>}
                    <span className="symbol-text" title={data.symbol}>{data.symbol}</span>
                </div>

                <div className={`symbol-price${price.length > 15 ? " long" : ""}`} title={price}>
                    {price}
                </div>

                <div className="symbol-type">
                    {data.type}
                </div>

                <div className={`symbol-change ${changeClass(data.change_pct)}`}>
                    {change} <span className="symbol-change-pct">({changePct})</span>
                </div>

                {selected ? (
                    <span className="selected-badge">Selected</span>
                ) : (
                    <button className="btn btn-primary select-btn" onClick={select}>
                        Select
                    </button>
                )}
            </div>
        </div>
    )
}

export default TransactionSymbolItem
