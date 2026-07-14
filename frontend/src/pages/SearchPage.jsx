import "../css/Search.css"
import {useState} from "react";
import {searchCrypto, searchStock} from "../services/api.js";

function SearchPage (){
    const [searchSymbol, setSearchSymbol] = useState({"symbol": ""});
    const [searchResults, setSearchResults] = useState([])


    function searchBarChange(e){
        setSearchSymbol({
            "symbol": e,
        })
    }

    async function searchBarSubmit(){
        const data = await searchStock(searchSymbol.symbol)
        setSearchResults(data)
    }

    return (
        <div className="search-page-wrapper">
            <div className="search-area">
                <div>
                    <button>Crypto</button>
                    <button>Stock</button>
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
