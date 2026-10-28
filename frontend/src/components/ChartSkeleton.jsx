// A chart's place while it loads: a faint made-up line and its fill with a light sweeping over them, so the page
// keeps its shape (a lone spinner made it look empty). `label` is what a screen reader hears.
function ChartSkeleton({label = "Loading chart…"}) {
    return (
        <div className="chart-skeleton" role="status">
            <svg viewBox="0 0 400 160" preserveAspectRatio="none" aria-hidden="true">
                <path d="M0 120 C40 112 60 92 100 98 S170 70 200 78 S270 40 300 52 S360 30 400 24 L400 160 L0 160 Z"
                      fill="rgba(255,255,255,0.035)"/>
                <path d="M0 120 C40 112 60 92 100 98 S170 70 200 78 S270 40 300 52 S360 30 400 24"
                      fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="2" vectorEffect="non-scaling-stroke"/>
            </svg>
            <span className="visually-hidden">{label}</span>
        </div>
    );
}

export default ChartSkeleton;
