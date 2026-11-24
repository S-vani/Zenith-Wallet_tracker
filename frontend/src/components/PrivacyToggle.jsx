import {useState} from "react";
import {amountsHidden, toggleAmountsHidden} from "../utils/privacy.js";
import {haptic} from "../native/haptics.js";

// The eye next to "Portfolio value": hides or shows every amount of the person's own money (utils/privacy.js)
function PrivacyToggle() {
    const [hidden, setHidden] = useState(amountsHidden);
    return (
        <button type="button" className="privacy-toggle" aria-pressed={hidden}
                aria-label={hidden ? "Show amounts" : "Hide amounts"}
                onClick={() => {
                    setHidden(toggleAmountsHidden());
                    haptic("light");
                }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"
                 strokeLinejoin="round" aria-hidden="true">
                <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/>
                <circle cx="12" cy="12" r="3"/>
                {hidden && <path d="M4 4l16 16"/>}
            </svg>
        </button>
    );
}

export default PrivacyToggle;
