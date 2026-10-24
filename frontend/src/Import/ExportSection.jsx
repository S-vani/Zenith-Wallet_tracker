import {useState} from "react";
import {exportTradesCsv, getImportTemplate} from "../services/api.js";
import {showToast} from "../utils/toast.js";
import {saveCsv} from "./saveCsv.js";

// Download every trade (Zenith's template, which imports back in) or an empty template to fill in by hand
function ExportSection() {
    const [busy, setBusy] = useState(null); // "export" | "template" while downloading
    const [error, setError] = useState(null);

    const download = async (kind) => {
        setBusy(kind);
        setError(null);
        try {
            const file = kind === "export" ? await exportTradesCsv() : await getImportTemplate();
            if (await saveCsv(file)) {
                showToast(kind === "export" ? "Your trades were downloaded" : "Template downloaded");
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setBusy(null);
        }
    };

    return (
        <section className="import-card" aria-labelledby="export-heading">
            <h2 id="export-heading" className="import-card-title">Export</h2>
            <p className="import-text">
                Download all your trades as a CSV file you can open in any spreadsheet or import back into Zenith.
                Prices are the ones you entered, in the currency you entered them in.
            </p>
            <div className="import-buttons">
                <button type="button" className="btn btn-primary" onClick={() => download("export")}
                        disabled={busy !== null} aria-busy={busy === "export"}>
                    {busy === "export" ? "Preparing…" : "Download all trades (CSV)"}
                </button>
                <button type="button" className="btn" onClick={() => download("template")}
                        disabled={busy !== null} aria-busy={busy === "template"}>
                    {busy === "template" ? "Preparing…" : "Download template"}
                </button>
            </div>
            {error && <p className="alert-error" role="alert">{error}</p>}
        </section>
    );
}

export default ExportSection;
