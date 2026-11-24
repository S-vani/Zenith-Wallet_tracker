import {useEffect, useId, useMemo, useRef, useState} from "react";
import RollingNumber from "../components/RollingNumber.jsx";
import {ACCOUNT_TYPES} from "../utils/accounts.js";
import {formatMoney} from "../utils/format.js";
import {haptic} from "../native/haptics.js";
import {showToast} from "../utils/toast.js";
import {
    absorbText, accountsPresent, activeCount, activePills, activePreset, datePresets, EMPTY_FILTERS, facetCounts,
    summarize, toggleValue,
} from "./filterModel.js";
import {TRANSACTION_SORTS} from "./transactionSort.js";
import {ACTION_LABELS, KIND_LABELS, labelFor} from "./filterLabels.js";

const ACCOUNT_ORDER = ACCOUNT_TYPES.map((a) => a.value);
// One toggle chip with its live count. A chip that would show nothing is dimmed (still usable, it can be switched off).
function Chip({label, count, on, onClick}) {
    const dim = !on && count === 0;
    return (
        <button type="button" className={`fchip${on ? " on" : ""}${dim ? " dim" : ""}`} aria-pressed={on}
                onClick={onClick}>
            {label}
            {count !== undefined && <span className="fchip-count">{count}</span>}
        </button>
    );
}

// The filter system for the trade list (see filterModel.js): a search bar that turns words into filters, chips with
// live counts, an advanced panel (dates, amounts, sort), removable pills and a summary of what is shown.
function FilterBar({trades, shown, filters, onChange, sort, onSort, currency}) {
    const [text, setText] = useState(filters.q);
    const [panelOpen, setPanelOpen] = useState(false);
    const panelId = useId();
    const inputRef = useRef(null);
    const panelRef = useRef(null);
    const panelButtonRef = useRef(null);

    // the box follows the symbol filter when it changes from elsewhere (a pill, "Clear all", the address)
    const [syncedQ, setSyncedQ] = useState(filters.q);
    if (filters.q !== syncedQ) {
        setSyncedQ(filters.q);
        setText(filters.q);
    }

    const counts = useMemo(() => facetCounts(trades, filters), [trades, filters]);
    const accounts = useMemo(() => accountsPresent(trades, ACCOUNT_ORDER), [trades]);
    const summary = useMemo(() => summarize(shown), [shown]);
    const pills = useMemo(() => activePills(filters, labelFor), [filters]);
    const total = activeCount(filters);

    // "/" focuses the bar (outside text fields)
    useEffect(() => {
        const onKey = (e) => {
            if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
            const el = document.activeElement;
            if (el && (el.matches?.("input, textarea, select") || el.isContentEditable)) return;
            e.preventDefault();
            inputRef.current?.focus();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    // the panel closes on Escape or a click outside it
    useEffect(() => {
        if (!panelOpen) return;
        const onKey = (e) => {
            if (e.key === "Escape") {
                setPanelOpen(false);
                panelButtonRef.current?.focus();
            }
        };
        const onDown = (e) => {
            if (!panelRef.current?.contains(e.target) && !panelButtonRef.current?.contains(e.target)) setPanelOpen(false);
        };
        window.addEventListener("keydown", onKey);
        document.addEventListener("pointerdown", onDown);
        return () => {
            window.removeEventListener("keydown", onKey);
            document.removeEventListener("pointerdown", onDown);
        };
    }, [panelOpen]);

    const toggle = (group, value) => {
        haptic("light");
        onChange(toggleValue(filters, group, value));
    };

    // typing: a space or Enter turns the recognised words into chips; the rest filters by symbol as you type
    const typed = (value, commit) => {
        if (!commit && !/\s$/.test(value)) {
            setText(value);
            onChange({...filters, q: value});
            return;
        }
        const {filters: next, rest} = absorbText({...filters, q: ""}, value);
        setText(rest);
        onChange({...next, q: rest});
    };

    const onKeyDown = (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            typed(text, true);
        } else if (e.key === "Escape" && text) {
            e.preventDefault();
            setText("");
            onChange({...filters, q: ""});
        } else if (e.key === "Backspace" && text === "" && pills.length > 0) {
            onChange(pills[pills.length - 1].off(filters)); // takes the last chip off
        }
    };

    const clearAll = () => {
        const before = filters;
        haptic("medium");
        onChange(EMPTY_FILTERS);
        setText("");
        showToast("Filters cleared", {action: {label: "Undo", run: () => onChange(before)}});
    };

    const preset = activePreset(filters);

    return (
        <section className="fbar" aria-label="Filter trades">
            <div className="fbar-row">
                <div className="fsearch">
                    <svg className="fsearch-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                        <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2"/>
                        <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                    <input ref={inputRef} type="search" className="fsearch-input" value={text}
                           placeholder="Search, or try “buy tfsa 2026”"
                           aria-label="Search trades"
                           autoComplete="off" autoCapitalize="none" spellCheck="false" enterKeyHint="search"
                           onChange={(e) => typed(e.target.value, false)} onKeyDown={onKeyDown}/>
                    <kbd className="fsearch-key" aria-hidden="true">/</kbd>
                </div>

                <label className="fsort">
                    <span className="visually-hidden">Sort trades</span>
                    <select value={sort} onChange={(e) => onSort(e.target.value)}>
                        {TRANSACTION_SORTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                </label>

                <button type="button" ref={panelButtonRef} className={`fpanel-button${panelOpen ? " on" : ""}`}
                        aria-expanded={panelOpen} aria-controls={panelId} onClick={() => setPanelOpen(!panelOpen)}>
                    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                        <path d="M4 7h10M18 7h2M4 17h2M10 17h10" stroke="currentColor" strokeWidth="2"
                              strokeLinecap="round" fill="none"/>
                        <circle cx="16" cy="7" r="2.2" fill="none" stroke="currentColor" strokeWidth="2"/>
                        <circle cx="8" cy="17" r="2.2" fill="none" stroke="currentColor" strokeWidth="2"/>
                    </svg>
                    <span className="fpanel-label">Filters</span>
                    {total > 0 && <span className="fpanel-badge">{total}</span>}
                </button>

                {panelOpen && (
                    <div className="fpanel" id={panelId} ref={panelRef} role="dialog" aria-label="Filters">
                        <div className="fpanel-grabber" aria-hidden="true"/>
                        <div className="fpanel-head">
                            <strong>Filters</strong>
                            <button type="button" className="fpanel-done" onClick={() => setPanelOpen(false)}>Done</button>
                        </div>

                        <fieldset className="fpanel-group">
                            <legend>Date</legend>
                            <div className="fpanel-presets">
                                {datePresets().map((p) => (
                                    <button key={p.id} type="button" className={`fchip${preset?.id === p.id ? " on" : ""}`}
                                            aria-pressed={preset?.id === p.id}
                                            onClick={() => onChange(preset?.id === p.id
                                                ? {...filters, from: "", to: ""} : {...filters, from: p.from, to: p.to})}>
                                        {p.label}
                                    </button>
                                ))}
                            </div>
                            <div className="fpanel-pair">
                                <label>
                                    <span>From</span>
                                    <input type="date" value={filters.from} max={filters.to || undefined}
                                           onChange={(e) => onChange({...filters, from: e.target.value})}/>
                                </label>
                                <label>
                                    <span>To</span>
                                    <input type="date" value={filters.to} min={filters.from || undefined}
                                           onChange={(e) => onChange({...filters, to: e.target.value})}/>
                                </label>
                            </div>
                        </fieldset>

                        <fieldset className="fpanel-group">
                            <legend>Trade size</legend>
                            <div className="fpanel-pair">
                                <label>
                                    <span>At least</span>
                                    <input type="text" inputMode="decimal" placeholder="0" value={filters.min}
                                           onChange={(e) => onChange({...filters, min: e.target.value.replace(/[^\d.,]/g, "")})}/>
                                </label>
                                <label>
                                    <span>At most</span>
                                    <input type="text" inputMode="decimal" placeholder="No limit" value={filters.max}
                                           onChange={(e) => onChange({...filters, max: e.target.value.replace(/[^\d.,]/g, "")})}/>
                                </label>
                            </div>
                        </fieldset>

                        <div className="fpanel-foot">
                            <span aria-live="polite">{shown.length} of {trades.length} trades</span>
                            <button type="button" className="fpanel-clear" disabled={total === 0} onClick={clearAll}>
                                Clear all
                            </button>
                        </div>
                    </div>
                )}
            </div>

            <div className="fchips" role="group" aria-label="Quick filters">
                {Object.keys(ACTION_LABELS).map((v) => (
                    <Chip key={v} label={ACTION_LABELS[v]} count={counts.actions[v] ?? 0}
                          on={filters.actions.includes(v)} onClick={() => toggle("actions", v)}/>
                ))}
                <span className="fchips-sep" aria-hidden="true"/>
                {Object.keys(KIND_LABELS).map((v) => (
                    <Chip key={v} label={KIND_LABELS[v]} count={counts.kinds[v] ?? 0}
                          on={filters.kinds.includes(v)} onClick={() => toggle("kinds", v)}/>
                ))}
                {accounts.length > 0 && <span className="fchips-sep" aria-hidden="true"/>}
                {accounts.map((v) => (
                    <Chip key={v} label={labelFor("accounts", v)} count={counts.accounts[v] ?? 0}
                          on={filters.accounts.includes(v)} onClick={() => toggle("accounts", v)}/>
                ))}
            </div>

            {pills.length > 0 && (
                <div className="fpills">
                    {pills.map((p) => (
                        <button key={p.key} type="button" className="fpill" aria-label={`Remove filter: ${p.label}`}
                                onClick={() => onChange(p.off(filters))}>
                            {p.label}<span aria-hidden="true">×</span>
                        </button>
                    ))}
                    <button type="button" className="fpills-clear" onClick={clearAll}>Clear all</button>
                </div>
            )}

            <p className="fsummary">
                <strong aria-live="polite" aria-atomic="true">
                    {total > 0 ? `${summary.count} of ${trades.length} trades` : `${summary.count} ${summary.count === 1 ? "trade" : "trades"}`}
                </strong>
                {summary.bought > 0 && (
                    <span>Bought <RollingNumber text={formatMoney(summary.bought, currency)}/></span>
                )}
                {summary.sold > 0 && (
                    <span>Sold <RollingNumber text={formatMoney(summary.sold, currency)}/></span>
                )}
            </p>
        </section>
    );
}

export default FilterBar;
