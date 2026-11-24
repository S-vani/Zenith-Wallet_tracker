// The X-Ray's 0-100 diversification score as a ring that fills up when it appears (Xray.css). Green from 75,
// amber from 50, red below. `size` is "lg" (the X-Ray page) or "sm" (the dashboard card).
function ScoreRing({score, size = "lg"}) {
    const radius = 42;
    const circumference = 2 * Math.PI * radius;
    const tone = score >= 75 ? "good" : score >= 50 ? "fair" : "poor";
    return (
        <span className={`score-ring ${size} ${tone}`} role="img" aria-label={`Diversification score ${score} of 100`}>
            <svg viewBox="0 0 100 100" aria-hidden="true">
                <circle className="score-ring-track" cx="50" cy="50" r={radius}/>
                <circle className="score-ring-fill" cx="50" cy="50" r={radius}
                        style={{"--dash": circumference, "--offset": circumference * (1 - score / 100)}}/>
            </svg>
            <span className="score-ring-value" aria-hidden="true">{score}</span>
        </span>
    );
}

export default ScoreRing;
