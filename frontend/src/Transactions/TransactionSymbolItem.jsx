import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatPercent, formatPrice, formatSignedMoney, listingName} from "../utils/format.js";
import {symbolSelection} from "./tradeForm.js";

function TransactionSymbolItem({data, onSub, selected = false}) {
    const {currency} = useUser();

    const select = () => onSub(symbolSelection(data), data);

    const price = formatPrice(data.price, currency);
    const change = formatSignedMoney(data.change, currency);
    const changePct = formatPercent(data.change_pct);
    const listing = listingName(data);

    return (
        <div className={`transaction-symbol-item-wrapper${selected ? " selected" : ""}`}>
            <div className="symbol-card-grid">

                <div className="symbol-cell">
                    {data.image && <img className="symbol-image" src={data.image} alt=""/>}
                    {/* the name tells apart tickers like "SHOP" vs "SHOP.TO", or coins that share a symbol */}
                    <span className="symbol-names">
                        <span className="symbol-text" title={data.symbol}>{data.symbol}</span>
                        {listing && <span className="symbol-name" title={listing}>{listing}</span>}
                    </span>
                </div>

                <div className={`symbol-price${price.length > 15 ? " long" : ""}`} title={price}>
                    {price}
                </div>

                <div className="symbol-type">
                    {data.type}
                </div>

                <div className={`symbol-change ${changeClass(data.change_pct)}`}>
                    {/* sub-cent moves on tiny coins would just read "CA$0.00", so show only the % */}
                    {Math.abs(data.change) >= 0.005
                        ? <>{change} <span className="symbol-change-pct">({changePct})</span></>
                        : <span className="symbol-change-pct">{changePct}</span>}
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
