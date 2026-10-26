import HoldingsItem, {Amount} from "./HoldingsItem.jsx";
import {useUser} from "../context/UserContext.jsx";
import {changeClass, formatMoney, formatPercent, formatSignedMoney} from "../utils/format.js";
import {holdingsTotals} from "./holdingsTotals.js";


// Sum of the priced holdings, lined up under the list's columns. Screen readers get it as one sentence (the visual
// cells rely on the column header, which is hidden from them)
function HoldingsTotals({holdings}) {
    const {currency} = useUser();
    const {value, gain, gainPct, unpriced} = holdingsTotals(holdings);
    const hasTotals = value !== null;

    const valueText = hasTotals ? formatMoney(value, currency) : "—";
    const gainText = hasTotals ? formatSignedMoney(gain, currency) : "—";
    const pctText = gainPct === null ? "—" : formatPercent(gainPct);
    const classReturn = `change-pct ${changeClass(gain)}`;
    const leftOut = unpriced.length > 0 && (
        `${unpriced.length === 1 ? "1 holding has" : `${unpriced.length} holdings have`} no price and ` +
        `${unpriced.length === 1 ? "is" : "are"} left out: ${unpriced.join(", ")}.`
    );

    return (
        <section className="holdings-totals" aria-label="Totals">
            <p className="visually-hidden">
                {hasTotals
                    ? `Total value ${valueText}, total return ${gainText} (${pctText}).`
                    : "No totals: none of your holdings has a price right now."}
            </p>
            <div className="holdings-totals-row" aria-hidden="true">
                <span className="holdings-totals-label">Total</span>
                <span className="holding-cell" data-label="Total value">
                    {hasTotals ? <Amount text={valueText}/> : "—"}
                </span>
                <span className="holdings-totals-spacer"/>
                <span className="holdings-totals-spacer"/>
                <span className={`holding-cell ${classReturn}`} data-label="Total return">
                    {hasTotals ? <Amount text={gainText}/> : "—"}
                </span>
                <span className={`holding-cell ${classReturn}`} data-label="Return %">
                    {gainPct === null ? "—" : <Amount text={pctText}/>}
                </span>
                <span/>
            </div>
            {leftOut && <p className="holdings-totals-note">{leftOut}</p>}
            {/* the two "returns" differ on purpose; without this people took the gap for a bug */}
            {hasTotals && (
                <p className="holdings-totals-note">
                    Total return is unrealized only: what you still hold, against what you paid for it. The
                    dashboard's all-time return also counts gains and losses from what you've sold.
                </p>
            )}
        </section>
    );
}

function HoldingsList({holdings}) {

    // biggest positions first, ones with no price (null) last
    const value = (h) => h.current_price ?? -Infinity;
    const sorted = [...holdings].sort((a, b) => value(b) - value(a) || 0);

    return (
        <>
            <div className="holdings-list-items">
                {sorted.map((t, i) => (
                    <HoldingsItem
                        key={`${t.type}-${t.symbol}`}
                        holding={t}
                        index={i}
                    />
                ))}
            </div>
            <HoldingsTotals holdings={holdings}/>
        </>
    )
}

export default HoldingsList
