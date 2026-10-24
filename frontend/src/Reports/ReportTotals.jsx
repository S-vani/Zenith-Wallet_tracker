import {changeClass} from "../utils/format.js";
import {cad, inclusionLine, signedCad} from "./reportUtils.js";

// The year's totals as cards, then the informational 50% inclusion line
function ReportTotals({totals, year}) {
    const cards = [
        {label: "Proceeds", value: cad(totals.proceeds)},
        {label: "Adjusted cost base", value: cad(totals.acb)},
        {label: "Net gain or loss", value: signedCad(totals.net), tone: changeClass(totals.net), main: true},
        {label: "Gains", value: signedCad(totals.gains), tone: changeClass(totals.gains)},
        {label: "Losses", value: signedCad(totals.losses), tone: changeClass(totals.losses)},
    ];

    return (
        <section className="reports-totals" aria-labelledby="reports-totals-title">
            <h2 id="reports-totals-title" className="reports-section-title">Totals for {year}</h2>
            <dl className="reports-cards-grid">
                {cards.map(({label, value, tone, main}) => (
                    <div key={label} className={`reports-total${main ? " is-main" : ""}`}>
                        <dt className="reports-total-label">{label}</dt>
                        <dd className={`reports-total-value ${tone ?? ""}`}>{value}</dd>
                    </div>
                ))}
            </dl>
            <p className="reports-inclusion">
                {inclusionLine(totals)} <span className="reports-muted">For information only, not tax advice.</span>
            </p>
        </section>
    );
}

export default ReportTotals;
