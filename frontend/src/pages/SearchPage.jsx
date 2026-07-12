import "../css/Search.css"
import {useState} from "react";

function SearchPage (){
    const [searchSymbol, setSearchSymbol] = useState({"symbol": ""});


    function searchBarChange(e){
        setSearchSymbol({
            "symbol": e,
        })
        console.log(e)
    }

    return (
        <div className="search-page-wrapper">
            <input onChange={(e) => searchBarChange(e.target.value)} className="search-bar" placeholder="Insert Symbol"/>
        </div>
    )
}

export default SearchPage
