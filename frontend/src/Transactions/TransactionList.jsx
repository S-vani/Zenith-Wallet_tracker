import TransactionItem from "./TransactionItem.jsx";

function TransactionList({transactions, onChanged}) {
    return (
        <div className="transaction-list">
            {transactions.map((t, i) => (
                <TransactionItem key={t.id} transaction={t} index={i} onChanged={onChanged}/>
            ))}
        </div>
    )
}

export default TransactionList
