import {changeClass, formatQuantity} from "../utils/format.js";
import {cad, saleFlags, securityLabel, signedCad} from "./reportUtils.js";

// The warning labels plus the server's explanation of each, and CRA's page for a possible superficial loss
function SaleNotes({sale, craUrl}) {
    const flags = saleFlags(sale);
    if (flags.length === 0 && sale.notes.length === 0) return <span className="reports-muted">—</span>;

    return (
        <div className="reports-sale-notes">
            {flags.length > 0 && (
                <ul className="reports-flags" aria-label="Warnings">
                    {flags.map(({kind, label}) => (
                        <li key={kind} className={`reports-flag reports-flag-${kind}`}>{label}</li>
                    ))}
                </ul>
            )}
            {sale.notes.map((note) => <p key={note}>{note}</p>)}
            {sale.superficial_loss && craUrl && (
                <a className="inline-link" href={craUrl} target="_blank" rel="noopener noreferrer">
                    CRA: superficial losses<span className="visually-hidden"> (opens in a new tab)</span>
                </a>
            )}
        </div>
    );
}

// A table on wider screens and a list of cards on phones. Only one is displayed (the other is display: none, so
// screen readers don't hear every sale twice).
function SalesTable({sales, year, craUrl}) {
    return (
        <section className="reports-sales" aria-labelledby="reports-sales-title">
            <h2 id="reports-sales-title" className="reports-section-title">Sales in {year}</h2>

            {/* focusable so keyboard users can scroll it sideways when it's wider than the screen */}
            <div className="reports-table-wrap" tabIndex={0} role="region" aria-labelledby="reports-table-caption">
                <table className="reports-table">
                    <caption id="reports-table-caption" className="visually-hidden">
                        Taxable sales in {year}, amounts in Canadian dollars
                    </caption>
                    <thead>
                        <tr>
                            <th scope="col">Date (UTC)</th>
                            <th scope="col">Security</th>
                            <th scope="col" className="num">Quantity</th>
                            <th scope="col" className="num">Proceeds</th>
                            <th scope="col" className="num">ACB</th>
                            <th scope="col" className="num">Gain or loss</th>
                            <th scope="col">Notes</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sales.map((sale) => (
                            <tr key={sale.id} className={saleFlags(sale).length ? "has-warning" : undefined}>
                                <td className="nowrap">{sale.date}</td>
                                <th scope="row" className="reports-symbol">{securityLabel(sale)}</th>
                                <td className="num">{formatQuantity(sale.quantity)}</td>
                                <td className="num">{cad(sale.proceeds)}</td>
                                <td className="num">{cad(sale.acb)}</td>
                                <td className={`num ${changeClass(sale.gain)}`}>{signedCad(sale.gain)}</td>
                                <td className="reports-notes-cell"><SaleNotes sale={sale} craUrl={craUrl}/></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <ul className="reports-sale-cards">
                {sales.map((sale) => (
                    <li key={sale.id} className="reports-sale-card">
                        <div className="reports-sale-head">
                            <h3 className="reports-symbol">{securityLabel(sale)}</h3>
                            <span className="reports-muted">{sale.date} (UTC)</span>
                        </div>
                        <dl className="reports-sale-figures">
                            <div><dt>Quantity</dt><dd>{formatQuantity(sale.quantity)}</dd></div>
                            <div><dt>Proceeds</dt><dd>{cad(sale.proceeds)}</dd></div>
                            <div><dt>ACB</dt><dd>{cad(sale.acb)}</dd></div>
                            <div>
                                <dt>Gain or loss</dt>
                                <dd className={changeClass(sale.gain)}>{signedCad(sale.gain)}</dd>
                            </div>
                        </dl>
                        {(sale.notes.length > 0 || saleFlags(sale).length > 0) && (
                            <SaleNotes sale={sale} craUrl={craUrl}/>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    );
}

export default SalesTable;
