import "../css/Search.css"
import {useState} from "react";
import {searchCrypto, searchStock} from "../services/api.js";

function SearchPage (){
    const [searchSymbol, setSearchSymbol] = useState({"symbol": "", "type": ""});
    const [searchResults, setSearchResults] = useState([])


    function searchBarChange(e){
        setSearchSymbol({
            ...searchSymbol,
            "symbol": e,
        })
    }

    async function searchBarSubmit(){
        let data;
        if (searchSymbol.type === "stock"){
            data = await searchStock(searchSymbol.symbol)
        }
        else if (searchSymbol.type === "crypto"){
            data = await searchCrypto(searchSymbol.symbol)
        }
        else{
            throw new Error("Please select which type of holding you are searching for.")
        }

        setSearchResults(data)
    }

    return (
        <div className="search-page-wrapper">
            <div className="search-area">
                <div>
                    <button
                        className={searchSymbol.type === "crypto" ? "search-button active": "search-button"}
                        onClick={() => setSearchSymbol({
                        ...searchSymbol,
                        "type": "crypto"
                    })}>
                        Crypto
                    </button>
                    <button
                        className={searchSymbol.type === "stock" ? "search-button active": "search-button"}
                        onClick={() => setSearchSymbol({
                        ...searchSymbol,
                        "type": "stock"
                    })}>
                        Stock
                    </button>
                </div>
                <input
                    onChange={(e) => searchBarChange(e.target.value)}
                    className="search-bar"
                    placeholder="Insert Symbol"
                />
            </div>

            <button className="search-submit-button" onClick={() => searchBarSubmit()}>Search</button>

            <button onClick={() => console.log(searchResults)}>Hello</button>
        </div>
    )
}

export default SearchPage
