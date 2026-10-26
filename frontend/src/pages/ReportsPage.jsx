import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {getCapitalGainsCsv, getCapitalGainsReport, getCapitalGainsYears} from "../services/api.js";
import usePageTitle from "../utils/usePageTitle.js";
import useRefreshKey from "../native/useRefreshKey.js";
import {showToast} from "../utils/toast.js";
import ReportTotals from "../Reports/ReportTotals.jsx";
import SalesTable from "../Reports/SalesTable.jsx";
import {pickYear, plural, warningCounts} from "../Reports/reportUtils.js";
import {saveCsv} from "../Reports/saveCsv.js";

import "../css/Reports.css";

// Capital gains report for Canadian taxes: taxable (non-registered or not set) sales settling in one year with
// their ACB, always in CAD. The page's <main> comes from the signed-in layout (App.jsx).
function ReportsPage() {
    usePageTitle("Tax report");

    const [years, setYears] = useState(null); // null until loaded
    const [yearsError, setYearsError] = useState(null);
    const [year, setYear] = useState(null);
    const [report, setReport] = useState(null);
    const [reportError, setReportError] = useState(null);
    const [attempt, setAttempt] = useState(0); // bumped by "Try again"
    const [downloading, setDownloading] = useState(false);
    const refreshKey = useRefreshKey(); // app only: pull to refresh / coming back to the app

    useEffect(() => {
        let ignore = false;
        getCapitalGainsYears()
            .then((list) => {
                if (ignore) return;
                setYears(list);
                setYearsError(null);
                // keep the year being looked at when it still has sales (e.g. after a refresh)
                setYear((current) => pickYear(list, current));
            })
            .catch((err) => {
                if (!ignore) setYearsError(err.message);
            });
        return () => {
            ignore = true;
        };
    }, [refreshKey, attempt]);

    useEffect(() => {
        if (year === null) return undefined;
        let ignore = false;
        getCapitalGainsReport(year)
            .then((data) => {
                if (ignore) return;
                setReport(data);
                setReportError(null);
            })
            .catch((err) => {
                if (!ignore) setReportError(err.message);
            });
        return () => {
            ignore = true;
        };
    }, [year, refreshKey, attempt]);

    const retry = () => {
        setYearsError(null);
        setReportError(null);
        setAttempt((n) => n + 1);
    };

    const download = async () => {
        setDownloading(true);
        try {
            await saveCsv(await getCapitalGainsCsv(year));
        } catch (err) {
            showToast(err.message, {type: "error"});
        } finally {
            setDownloading(false);
        }
    };

    const error = yearsError ?? reportError;
    const errorAlert = error && (
        <div className="alert-error alert-retry" role="alert">
            <span>{error}</span>
            <button type="button" className="btn" onClick={retry}>Try again</button>
        </div>
    );
    // the report on screen belongs to the selected year (a new one is loading otherwise)
    const shown = report && report.year === year ? report : null;

    let content;
    if (years === null || (year !== null && !shown)) {
        content = error ? errorAlert : (
            <div className="state-message" role="status">
                <div className="spinner" aria-hidden="true"/>
                Loading your tax report…
            </div>
        );
    } else if (years.length === 0) {
        content = (
            <div className="state-message reports-empty">
                <strong>No taxable sales yet</strong>
                <p>
                    Only sales in a non-registered account, or with no account set, count for capital gains.
                    TFSA, RRSP, FHSA and RESP trades are left out.
                </p>
                <p>
                    To set the account of a trade, edit it on the Transactions page and pick one under "Account".
                </p>
                <Link to="/transactions" className="btn btn-primary">Go to Transactions</Link>
            </div>
        );
    } else {
        const counts = warningCounts(shown.sales);
        content = (
            <>
                {errorAlert}
                <ReportTotals totals={shown.totals} year={shown.year}/>

                {(shown.warnings ?? []).map((warning) => (
                    <p key={warning} className="alert-warning reports-warning-summary">{warning}</p>
                ))}

                {Object.values(counts).some((n) => n > 0) && (
                    <div className="alert-warning reports-warning-summary">
                        <strong>Please review: </strong>
                        {[
                            counts.oversold > 0 && `${plural(counts.oversold, "sale")} sold more than your taxable `
                            + "trades held (check the account types of earlier buys)",
                            counts.superficial > 0 && plural(counts.superficial, "possible superficial loss",
                                "possible superficial losses"),
                            counts.acb > 0 && `${plural(counts.acb, "sale")} whose ACB may be too low after a `
                            + "superficial loss",
                            counts.interlisted > 0 && `${plural(counts.interlisted, "sale")} of shares also traded `
                            + "under another listing",
                            counts.foreign > 0 && `${plural(counts.foreign, "sale")} involving USD or EUR amounts`,
                        ].filter(Boolean).join(" · ")}
                        .
                    </div>
                )}

                {shown.sales.length > 0
                    ? <SalesTable sales={shown.sales} year={shown.year} craUrl={shown.superficial_loss_url}/>
                    : <p className="state-message">No taxable sales in {shown.year}.</p>}

                <section className="reports-about" aria-labelledby="reports-about-title">
                    <h2 id="reports-about-title" className="reports-section-title">How this report works</h2>
                    <ul>
                        <li>
                            Amounts are in Canadian dollars whatever your display currency, because Canadian tax
                            is reported in CAD.
                        </li>
                        <li>
                            Each sale is in the tax year of its settlement date ("Settles"): one business day after
                            a stock trade (two before May 28, 2024), the trade date itself for crypto.
                        </li>
                        {shown.notes.map((note) => <li key={note}>{note}</li>)}
                        <li>
                            A superficial loss can be denied when you, your spouse or another affiliated person
                            buys the same security within 30 days before or after the sale and still owns it 30
                            days after.{" "}
                            <a className="reports-link" href={shown.superficial_loss_url} target="_blank"
                               rel="noopener noreferrer">
                                Read CRA's explanation
                                <span className="visually-hidden"> (opens in a new tab)</span>
                            </a>.
                        </li>
                    </ul>
                </section>
            </>
        );
    }

    return (
        <div className="app-page reports-page">
            <header className="reports-header">
                <div>
                    <h1 className="page-headers">Tax report</h1>
                    <p className="page-subtitle">Capital gains (Canada) from your non-registered trades, in CAD.</p>
                </div>
                {years?.length > 0 && (
                    <div className="reports-toolbar">
                        <label className="reports-year">
                            <span>Tax year</span>
                            <select value={year ?? ""} onChange={(e) => setYear(Number(e.target.value))}>
                                {years.map((y) => <option key={y} value={y}>{y}</option>)}
                            </select>
                        </label>
                        <button type="button" className="btn btn-primary" onClick={download}
                                disabled={downloading || year === null} aria-busy={downloading}>
                            {downloading ? "Preparing…" : "Download CSV"}
                        </button>
                    </div>
                )}
            </header>

            <p className="alert-warning reports-disclaimer">
                Not tax advice. Check these numbers against your broker's T5008 and other tax slips before you file.
                Commissions aren't stored in Zenith, so outlays and expenses are shown as $0.
            </p>

            {content}
        </div>
    );
}

export default ReportsPage;
