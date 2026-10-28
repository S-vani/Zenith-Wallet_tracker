import HoldingsChart from "./HoldingsChart.jsx"
import AssetAvatar from "../components/AssetAvatar.jsx";
import {useState} from "react";
import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatPercent, formatPrice, formatQuantity, formatSignedMoney} from "../utils/format.js";
import {AVG_COST_NOTE, averageCost, isPriced} from "./holdingsTotals.js";

// One unbreakable amount: on the website it shrinks with its cell by its length (--chars, see Holdings.css)
// instead of wrapping between digits ("CA$479,158,262," / "703.04"). The app shrinks it with fitNumbers.js instead
export function Amount({text}) {
    return (
        <span className="cell-amount" style={{"--chars": text.length}}
              title={text.length > 14 ? text : undefined}>{text}</span>
    );
}

function HoldingsItem({holding, index}) {
    const [isOpen, setIsOpen] = useState(false)
    const {currency} = useUser();

    // null current_price = no source has a price for it: show "—" instead of $0 / −100%
    const priced = isPriced(holding);
    const gain = priced ? holding.current_price - holding.price_paid : null;
    // null too when nothing was paid (free coins): a return % of nothing is unknown, not 0.00%
    const gainPct = priced && holding.price_paid > 0 ? (gain / holding.price_paid) * 100 : null;
    const classReturn = `change-pct ${changeClass(gain)}`;
    // per unit, so formatPrice: a tiny coin's average cost never shows as $0.00
    const avgCost = averageCost(holding);
    const avgCostText = avgCost === null ? "—" : formatPrice(avgCost, currency);

    return (
        <div className={`holding-item-wrapper${isOpen ? " open" : ""}`} style={{animationDelay: `${Math.min(index, 10) * 50}ms`}}>
            <button className="holding-item" onClick={() => setIsOpen(!isOpen)} aria-expanded={isOpen}>
                <div className="position-column">
                    <AssetAvatar symbol={holding.symbol} type={holding.type}/>
                    <div className="position-text">
                        <span className="position-symbol">{holding.symbol}</span>
                        <span className="position-type">{holding.type}</span>
                        {/* phones: the compact row says how many instead of the type */}
                        <span className="position-qty">{formatQuantity(holding.quantity)} {holding.type === "crypto" ? "coins" : "shares"}</span>
                    </div>
                </div>

                <span className="holding-cell" data-label="Value"
                      title={priced ? undefined : "Price unavailable"}>{priced ? <Amount text={formatMoney(holding.current_price, currency)}/> : "—"}</span>
                <span className="holding-cell" data-label="Quantity"><Amount text={formatQuantity(holding.quantity)}/></span>
                {/* a desktop column; phones have no room in the 2-column card, so it's in the expanded panel there */}
                <span className="holding-cell holding-avg-cost" data-label="Avg cost"
                      title={AVG_COST_NOTE}>{avgCost === null ? "—" : <Amount text={avgCostText}/>}</span>
                <span className={`holding-cell ${classReturn}`} data-label="Return">{priced ? <Amount text={formatSignedMoney(gain, currency)}/> : "—"}</span>
                <span className={`holding-cell ${classReturn}`} data-label="Return %">{gainPct !== null ? <Amount text={formatPercent(gainPct)}/> : "—"}</span>

                <span className="expand-icon" aria-hidden="true">▾</span>
            </button>

            {isOpen && (
                <div className="holding-chart-panel">
                    {/* phones: the compact row leaves these out, so the open panel has them */}
                    <p className="holding-panel-avg-cost">
                        Return <span className={`holding-panel-amount ${classReturn}`}>
                            {priced ? formatSignedMoney(gain, currency) : "—"}</span>
                    </p>
                    <p className="holding-panel-avg-cost">
                        Average cost <span className="holding-panel-amount">{avgCostText}</span>
                        {" "}per {holding.type === "stock" ? "share" : "coin"}
                    </p>
                    {/* TFSA and non-registered buys are averaged together here; the tax report has the ACB */}
                    <p className="holding-panel-note">{AVG_COST_NOTE}</p>
                    <HoldingsChart symbol={holding.symbol} type={holding.type} coinId={holding.coin_id}/>
                </div>
            )}
        </div>
    )
}

export default HoldingsItem
