import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {getPortfolioXray} from "../services/api.js";
import ScoreRing from "../Xray/ScoreRing.jsx";

import "../css/Xray.css";

// how long after the dashboard opens the X-Ray is asked for: the value card and chart load first
const LOAD_DELAY_MS = 1200;

// The dashboard's door to Portfolio X-Ray: the score ring and the most important finding. Renders nothing until
// there's an X-Ray to show (a new account, or the X-Ray failing, just leaves the dashboard as it was).
function XrayCard({currency}) {
    const [xray, setXray] = useState(null);

    useEffect(() => {
        if (!currency) return undefined;
        let ignore = false;
        const timer = setTimeout(() => {
            getPortfolioXray().then((data) => !ignore && setXray(data)).catch(() => null);
        }, LOAD_DELAY_MS);
        return () => {
            ignore = true;
            clearTimeout(timer);
        };
    }, [currency]);

    if (!xray || xray.empty) return null;
    const top = xray.findings[0];
    return (
        <Link to="/xray" className="xray-card">
            <ScoreRing score={xray.score.score} size="sm"/>
            <span className="xray-card-text">
                <small>Portfolio X-Ray</small>
                <strong>{xray.score.label}</strong>
                {top && <span>{top.title}</span>}
            </span>
            <span className="xray-card-chevron" aria-hidden="true">›</span>
        </Link>
    );
}

export default XrayCard;
