import TransactionItem from "./TransactionItem.jsx";

function TransactionList({transactions}) {
    return (
        <div className="transaction-list">
            {transactions.map((t, i) => (
                <TransactionItem key={t.id} transaction={t} index={i}/>
            ))}
        </div>
    )
}

export default TransactionList
