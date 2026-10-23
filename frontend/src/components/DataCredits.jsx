import {LegalLinks} from "./LegalLayout.jsx";

// Credits the data providers' free plans ask for: CoinGecko ("Powered by CoinGecko", linked) and ExchangeRate-API
// (a "Rates By Exchange Rate API" link on pages that show converted amounts). Shown under every signed-in page,
// with the Privacy / Terms / Support links under it (the app has no other footer that reaches them).
function DataCredits() {
    return (
        <>
            <p className="data-credits">
                Crypto data by{" "}
                <a href="https://www.coingecko.com/" target="_blank" rel="noopener noreferrer">CoinGecko</a>
                <span aria-hidden="true"> · </span>
                <a href="https://www.exchangerate-api.com" target="_blank" rel="noopener noreferrer">
                    Rates By Exchange Rate API
                </a>
                <span aria-hidden="true"> · </span>
                Prices may be delayed
            </p>
            <LegalLinks/>
        </>
    );
}

export default DataCredits;
