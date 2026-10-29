import TransactionSymbolItem from "./TransactionSymbolItem.jsx";

// The add-trade dialog's search results.
function TransactionSymbolList({data, onSub}) {
    return (
        <div className="transaction-symbol-list">
            {data.map(d => (
                <TransactionSymbolItem key={d.api_id} data={d} onSub={onSub}/>
            ))}
        </div>
    )
}

export default TransactionSymbolList
