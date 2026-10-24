import ImportSection from "../Import/ImportSection.jsx";
import ExportSection from "../Import/ExportSection.jsx";
import usePageTitle from "../utils/usePageTitle.js";

import "../css/Import.css";

// /import: bring trades in from a CSV (Zenith's template or a broker export) and download them all again, so
// nobody has to type their history in by hand or worry about their data being stuck here
function ImportPage() {
    usePageTitle("Import & export");

    return (
        <div className="app-page import-page">
            <header>
                <h1 className="page-headers">Import &amp; export</h1>
                <p className="page-subtitle">Bring in trades from a CSV file, or download all of yours.</p>
            </header>
            <ImportSection/>
            <ExportSection/>
        </div>
    );
}

export default ImportPage;
