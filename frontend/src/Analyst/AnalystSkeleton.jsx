// Placeholder with the same shape as the report (sentiment, insights, scenarios) while it loads
function AnalystSkeleton() {
    return (
        <div className="analyst-skeleton" aria-hidden="true">
            <div className="analyst-overview analyst-card">
                <div className="analyst-sentiment">
                    <span className="skeleton" style={{width: "7.5rem", height: "2.25rem"}}/>
                    <span className="skeleton" style={{width: "9rem", height: "0.9rem"}}/>
                    <span className="skeleton" style={{width: "100%", height: "0.5rem"}}/>
                </div>
                <div className="analyst-overview-text">
                    <span className="skeleton" style={{width: "100%", height: "0.95rem"}}/>
                    <span className="skeleton" style={{width: "94%", height: "0.95rem"}}/>
                    <span className="skeleton" style={{width: "70%", height: "0.95rem"}}/>
                    <span className="skeleton" style={{width: "55%", height: "0.8rem", marginTop: "0.5rem"}}/>
                    <span className="skeleton" style={{width: "60%", height: "0.8rem"}}/>
                </div>
            </div>

            <div className="analyst-section">
                <span className="skeleton" style={{width: "6.5rem", height: "0.8rem"}}/>
                <div className="analyst-insights">
                    {[0, 1, 2].map((i) => (
                        <div key={i} className="analyst-card analyst-skeleton-card">
                            <span className="skeleton" style={{width: "40%", height: "0.7rem"}}/>
                            <span className="skeleton" style={{width: "80%", height: "0.95rem"}}/>
                            <span className="skeleton" style={{width: "100%", height: "0.8rem"}}/>
                            <span className="skeleton" style={{width: "75%", height: "0.8rem"}}/>
                        </div>
                    ))}
                </div>
            </div>

            <div className="analyst-section">
                <span className="skeleton" style={{width: "5.5rem", height: "0.8rem"}}/>
                <div className="analyst-scenarios">
                    {[0, 1, 2].map((i) => (
                        <div key={i} className="analyst-card analyst-skeleton-card">
                            <span className="skeleton" style={{width: "45%", height: "0.95rem"}}/>
                            <span className="skeleton" style={{width: "100%", height: "0.8rem"}}/>
                            <span className="skeleton" style={{width: "85%", height: "0.8rem"}}/>
                            <span className="skeleton" style={{width: "100%", height: "2.5rem", marginTop: "0.4rem"}}/>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

export default AnalystSkeleton;
