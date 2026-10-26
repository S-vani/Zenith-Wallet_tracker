import {accountLabel} from "../utils/accounts.js";
import {formatPrice, formatQuantity} from "../utils/format.js";
import {STATUS_LABELS, isIncluded, rowDate, visibleRows} from "./importHelpers.js";

// The preview's rows: a table on wider screens, one card per row on phones (see Import.css). Ready rows and
// duplicates get an "Include" checkbox (ready ones start ticked, duplicates unticked), so any row can be left out;
// problem rows are never imported.
function ImportPreview({rows, toggled, onToggle, filter, onFilterChange}) {
    const {rows: shown, hidden, total} = visibleRows(rows, filter);

    return (
        <div className="import-preview">
            <div className="segmented import-filter" role="group" aria-label="Rows to show">
                <button type="button" className={filter === "all" ? "active" : ""} aria-pressed={filter === "all"}
                        onClick={() => onFilterChange("all")}>All rows</button>
                <button type="button" className={filter === "attention" ? "active" : ""}
                        aria-pressed={filter === "attention"} onClick={() => onFilterChange("attention")}>
                    Needs a look
                </button>
            </div>

            {total === 0 ? (
                <p className="import-text">Nothing needs a look: every row is ready.</p>
            ) : (
                <div className="import-table-wrap">
                    <table className="import-table">
                        <caption className="visually-hidden">Rows found in the file and what will happen to each</caption>
                        <thead>
                        <tr>
                            <th scope="col">Include</th>
                            <th scope="col">Line</th>
                            <th scope="col">Date</th>
                            <th scope="col">Trade</th>
                            <th scope="col">Quantity</th>
                            <th scope="col">Price</th>
                            <th scope="col">Account</th>
                            <th scope="col">Status</th>
                        </tr>
                        </thead>
                        <tbody>
                        {shown.map((row) => {
                            const what = `${row.action ?? ""} ${row.symbol ?? ""}`.trim() || "—";
                            return (
                                <tr key={row.line} className={`import-row is-${row.status}`}>
                                    <td data-label="Include" className="import-cell-include">
                                        {row.status === "ok" || row.status === "duplicate" ? (
                                            <input type="checkbox" checked={isIncluded(row, toggled)}
                                                   onChange={() => onToggle(row.line)}
                                                   aria-label={row.status === "duplicate"
                                                       ? `Include line ${row.line} (${what}) anyway`
                                                       : `Import line ${row.line} (${what})`}/>
                                        ) : (
                                            <span aria-hidden="true">—</span>
                                        )}
                                    </td>
                                    <td data-label="Line">{row.line}</td>
                                    <td data-label="Date">{rowDate(row.date, row.date_only)}</td>
                                    <td data-label="Trade" className="import-cell-trade">
                                        {row.action && <span className={`import-action is-${row.action.toLowerCase()}`}>{row.action}</span>}
                                        <span className="import-symbol">{(row.symbol ?? "—").toUpperCase()}</span>
                                    </td>
                                    <td data-label="Quantity">{row.quantity != null ? formatQuantity(row.quantity) : "—"}</td>
                                    <td data-label="Price">
                                        {row.price != null && row.currency ? formatPrice(row.price, row.currency) : "—"}
                                        {row.currency && <span className="import-currency"> {row.currency}</span>}
                                    </td>
                                    <td data-label="Account">{accountLabel(row.account_type)}</td>
                                    <td data-label="Status" className="import-cell-status">
                                        <span className={`import-status is-${row.status}`}>{STATUS_LABELS[row.status] ?? row.status}</span>
                                        {row.message && <span className="import-message">{row.message}</span>}
                                    </td>
                                </tr>
                            );
                        })}
                        </tbody>
                    </table>
                </div>
            )}
            {hidden > 0 && (
                <p className="import-text">
                    Showing the first {shown.length.toLocaleString()} of {total.toLocaleString()} rows. Ready rows that
                    aren't shown are still imported{filter === "all" ? "; choose “Needs a look” to see the rest of the problems and duplicates" : ""}.
                </p>
            )}
        </div>
    );
}

export default ImportPreview;
