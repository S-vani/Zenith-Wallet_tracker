import {useId, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {commitImport, previewImport} from "../services/api.js";
import {ACCOUNT_TYPES} from "../utils/accounts.js";
import {showToast} from "../utils/toast.js";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import ImportPreview from "./ImportPreview.jsx";
import {FORMAT_OPTIONS, fileProblem, formatLabel, importButtonLabel, plural, rowsToImport, summaryText} from "./importHelpers.js";

// Pick a CSV, see what every row would become (nothing is saved yet), then import the ready rows in one go.
function ImportSection() {
    const ids = {format: useId(), account: useId(), file: useId(), notes: useId()};
    const [format, setFormat] = useState("auto");
    const [defaultAccount, setDefaultAccount] = useState("");
    const [file, setFile] = useState(null); // {name, text}
    const [preview, setPreview] = useState(null); // the server's answer, plus the options it was made with
    const [included, setIncluded] = useState(() => new Set()); // duplicate lines the user ticked
    const [filter, setFilter] = useState("all");
    const [busy, setBusy] = useState(null); // "reading" | "previewing" | "importing"
    const [error, setError] = useState(null);
    const [imported, setImported] = useState(null); // how many the last import saved
    const [confirming, setConfirming] = useState(false);
    const [dragging, setDragging] = useState(false);
    const resultRef = useRef(null);
    const doneRef = useRef(null);

    const runPreview = async (text, chosenFormat = format, account = defaultAccount) => {
        setBusy("previewing");
        setError(null);
        try {
            const data = await previewImport(text, chosenFormat, account || null);
            setPreview({...data, format: chosenFormat, account});
            setIncluded(new Set());
            setFilter("all");
            // the result appears below the file picker: take keyboard and screen reader users there
            requestAnimationFrame(() => resultRef.current?.focus());
        } catch (err) {
            setPreview(null);
            setError(err.message);
        } finally {
            setBusy(null);
        }
    };

    const chooseFile = async (picked) => {
        setImported(null);
        const problem = fileProblem(picked);
        if (problem) {
            setError(problem);
            return;
        }
        setBusy("reading");
        let text;
        try {
            text = await picked.text();
        } catch {
            setBusy(null);
            setError("This file couldn't be read. Please try again.");
            return;
        }
        setFile({name: picked.name, text});
        await runPreview(text);
    };

    const toggle = (line) => {
        setIncluded((current) => {
            const next = new Set(current);
            if (next.has(line)) next.delete(line);
            else next.add(line);
            return next;
        });
    };

    const selected = preview ? rowsToImport(preview.rows, included) : [];
    const stale = Boolean(preview && file && (preview.format !== format || preview.account !== defaultAccount));

    const startOver = () => {
        setFile(null);
        setPreview(null);
        setIncluded(new Set());
        setError(null);
    };

    const runImport = async () => {
        setConfirming(false);
        setBusy("importing");
        setError(null);
        try {
            const result = await commitImport(selected);
            showToast(`Imported ${plural(result.imported, "trade")}`);
            setImported(result.imported);
            startOver();
            requestAnimationFrame(() => doneRef.current?.focus());
        } catch (err) {
            // e.g. a 409: the file would sell more of a symbol than was owned. Nothing was saved, the preview stays
            setError(err.message);
        } finally {
            setBusy(null);
        }
    };

    const onDrop = (event) => {
        event.preventDefault();
        setDragging(false);
        const dropped = event.dataTransfer?.files?.[0];
        if (dropped && !busy) chooseFile(dropped);
    };

    return (
        <section className="import-card" aria-labelledby="import-heading">
            <h2 id="import-heading" className="import-card-title">Import trades from a CSV</h2>

            <div className="import-options">
                <div className="import-field">
                    <label className="import-label" htmlFor={ids.format}>File format</label>
                    <select id={ids.format} className="import-select" value={format}
                            onChange={(e) => setFormat(e.target.value)} disabled={busy !== null}>
                        {FORMAT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>
                <div className="import-field">
                    <label className="import-label" htmlFor={ids.account}>Default account for rows without one</label>
                    <select id={ids.account} className="import-select" value={defaultAccount}
                            onChange={(e) => setDefaultAccount(e.target.value)} disabled={busy !== null}>
                        <option value="">Not set</option>
                        {ACCOUNT_TYPES.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>
            </div>

            <label htmlFor={ids.file} className={`import-drop${dragging ? " is-dragging" : ""}${busy ? " is-busy" : ""}`}
                   onDragOver={(e) => {
                       e.preventDefault();
                       if (!busy) setDragging(true);
                   }}
                   onDragLeave={() => setDragging(false)}
                   onDrop={onDrop}>
                <input id={ids.file} type="file" accept=".csv,text/csv" className="visually-hidden"
                       aria-describedby={ids.notes} disabled={busy !== null}
                       onChange={(e) => {
                           const picked = e.target.files?.[0];
                           e.target.value = ""; // so choosing the same file again (after fixing it) reads it again
                           if (picked) chooseFile(picked);
                       }}/>
                <span className="import-drop-title">
                    {busy === "reading" || busy === "previewing" ? "Reading your file…" : "Choose a CSV file"}
                </span>
                <span className="import-drop-sub">
                    {file ? `${file.name} · choose another file to replace it` : "or drop it here · up to 2 MB and 5,000 rows"}
                </span>
            </label>

            <ul className="import-notes" id={ids.notes}>
                <li>
                    <strong>Wealthsimple:</strong> download your activities export (CSV).{" "}
                    <strong>Questrade:</strong> export your account activity, then open the Excel file and save it as
                    CSV. Only buys and sells are imported; dividends, deposits and fees are skipped.
                </li>
                <li>Commissions and fees aren't imported: each trade keeps its quantity and unit price.</li>
                <li>
                    Prices in another currency are kept as entered and converted to CAD at the exchange rate of each
                    trade's date (today's rate if that one isn't available), the same as adding a trade by hand.
                </li>
                <li>Nothing is saved until you press Import and confirm.</li>
            </ul>

            {imported !== null && (
                <div className="alert-success import-done" role="status" tabIndex={-1} ref={doneRef}>
                    Imported {plural(imported, "trade")}. <Link to="/transactions" className="inline-link">See your
                    transactions</Link>
                </div>
            )}

            {error && <p className="alert-error" role="alert">{error}</p>}

            {preview && (
                <div className="import-result" tabIndex={-1} ref={resultRef} aria-labelledby="import-result-heading">
                    <div className="import-result-head">
                        <h3 id="import-result-heading" className="import-result-title">
                            Preview{file ? ` of ${file.name}` : ""}
                        </h3>
                        <p className="import-text">
                            Read as {formatLabel(preview.format_detected)}. {summaryText(preview.summary)}.
                        </p>
                        {stale && (
                            <div className="alert-warning import-stale">
                                The options changed since this preview.{" "}
                                <button type="button" className="btn" onClick={() => runPreview(file.text)}
                                        disabled={busy !== null}>Preview again</button>
                            </div>
                        )}
                    </div>

                    {preview.rows.length > 0 && (
                        <ImportPreview rows={preview.rows} included={included} onToggle={toggle}
                                       filter={filter} onFilterChange={setFilter}/>
                    )}

                    <div className="import-buttons">
                        <button type="button" className="btn btn-primary" onClick={() => setConfirming(true)}
                                disabled={busy !== null || selected.length === 0 || stale}
                                aria-busy={busy === "importing"}>
                            {busy === "importing" ? "Importing…" : importButtonLabel(selected.length)}
                        </button>
                        <button type="button" className="btn btn-ghost" onClick={startOver} disabled={busy !== null}>
                            Cancel
                        </button>
                    </div>
                </div>
            )}

            <ConfirmDialog
                open={confirming}
                title={`${importButtonLabel(selected.length)}?`}
                message="They'll be added to your trades, all together. If any of them would sell more than you owned at the time, nothing is saved."
                confirmLabel="Import"
                onConfirm={runImport}
                onCancel={() => setConfirming(false)}
            />
        </section>
    );
}

export default ImportSection;
