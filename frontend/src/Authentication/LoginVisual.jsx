// Decorative illustration for the login page: a portfolio card with a chart, with holdings floating around it.
// Built from the app's own card styles so it matches the dashboard instead of looking like clip art.

const CHART_LINE = "M0,92 C18,88 26,96 42,84 S70,70 86,74 S112,58 128,62 S152,44 170,48 S198,30 214,34 S244,18 262,22 S290,8 320,6";

// The decorative portfolio preview beside the login form (hidden from screen readers).
function LoginVisual() {
    return (
        <div className="login-visual" aria-hidden="true">
            <div className="login-visual-glow"/>

            <div className="lv-card lv-main">
                <div className="lv-row">
                    <span className="lv-label">Portfolio value</span>
                    <span className="lv-pill">1Y</span>
                </div>
                <div className="lv-value">$84,920.18</div>
                <div className="lv-change">▲ $9,213.42 (12.2%)</div>

                <svg className="lv-chart" viewBox="0 0 320 110" preserveAspectRatio="none">
                    <defs>
                        <linearGradient id="lvFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#22c55e" stopOpacity="0.35"/>
                            <stop offset="100%" stopColor="#22c55e" stopOpacity="0"/>
                        </linearGradient>
                    </defs>
                    <path d={`${CHART_LINE} L320,110 L0,110 Z`} fill="url(#lvFill)"/>
                    <path d={CHART_LINE} fill="none" stroke="#22c55e" strokeWidth="2.5" strokeLinecap="round"/>
                    <circle cx="320" cy="6" r="4" fill="#22c55e"/>
                </svg>

                <div className="lv-bars">
                    <span style={{"--w": "46%", "--c": "#93c5fd"}}/>
                    <span style={{"--w": "32%", "--c": "#22c55e"}}/>
                    <span style={{"--w": "22%", "--c": "#f59e0b"}}/>
                </div>
            </div>

            <div className="lv-card lv-chip lv-chip-top">
                <span className="lv-coin" style={{"--c": "#f59e0b"}}>₿</span>
                <div>
                    <div className="lv-chip-name">BTC</div>
                    <div className="lv-chip-sub">Crypto</div>
                </div>
                <span className="lv-up">+4.2%</span>
            </div>

            <div className="lv-card lv-chip lv-chip-bottom">
                <span className="lv-coin" style={{"--c": "#93c5fd"}}>A</span>
                <div>
                    <div className="lv-chip-name">AAPL</div>
                    <div className="lv-chip-sub">Stock</div>
                </div>
                <span className="lv-up">+1.8%</span>
            </div>
        </div>
    );
}

export default LoginVisual;
