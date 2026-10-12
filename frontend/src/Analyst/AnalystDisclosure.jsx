import {useId, useState} from "react";

// Collapsible section with a full-width toggle button (aria-expanded / aria-controls)
function AnalystDisclosure({title, hint, children, className = "", defaultOpen = false}) {
    const [open, setOpen] = useState(defaultOpen);
    const id = useId();

    return (
        <div className={`analyst-disclosure${open ? " open" : ""} ${className}`.trim()}>
            <button type="button" className="analyst-disclosure-toggle" aria-expanded={open} aria-controls={id}
                    onClick={() => setOpen(!open)}>
                <span className="analyst-disclosure-title">{title}</span>
                {hint && <span className="analyst-disclosure-hint">{hint}</span>}
                <svg className="analyst-disclosure-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="6 9 12 15 18 9"/>
                </svg>
            </button>
            <div id={id} className="analyst-disclosure-body" hidden={!open}>
                {open && children}
            </div>
        </div>
    );
}

export default AnalystDisclosure;
