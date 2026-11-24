import {useEffect, useState} from "react";
import {Link, useNavigate} from "react-router-dom";
import {
    deleteAlert, getAlerts, getNotifications, getNotificationSettings, markNotificationsRead, putNotificationSettings,
} from "../services/api.js";
import {useUser} from "../context/UserContext.jsx";
import {formatPrice} from "../utils/format.js";
import {showToast} from "../utils/toast.js";
import usePageTitle from "../utils/usePageTitle.js";
import {isNative} from "../native/platform.js";
import {enablePush, pushPermission, safeLink} from "../native/push.js";

import "../css/Alerts.css";

const KIND_ICONS = {alert: "🔔", event: "📅", briefing: "☀️"};

// "5 min ago", "3 h ago", "Yesterday", "Nov 18"
function timeAgo(iso) {
    const then = new Date(iso.endsWith("Z") ? iso : `${iso}Z`); // stored as naive UTC
    const minutes = Math.round((Date.now() - then.getTime()) / 60000);
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h ago`;
    if (minutes < 48 * 60) return "Yesterday";
    return then.toLocaleDateString(undefined, {month: "short", day: "numeric"});
}

// The alert's condition in words
function describe(alert, currency) {
    if (alert.kind === "move") return `moves ${alert.threshold}% or more in a day`;
    const price = formatPrice(alert.threshold, alert.currency ?? currency);
    return alert.kind === "above" ? `rises above ${price}` : `falls below ${price}`;
}

// Alerts: the inbox (price alerts that fired, earnings / dividend / trend events, the morning briefing), the
// alerts you've set, and what to be notified about. Opening it marks the inbox read.
function AlertsPage() {
    usePageTitle("Alerts");
    const navigate = useNavigate();
    const {currency} = useUser();
    const [inbox, setInbox] = useState(null);
    const [alerts, setAlerts] = useState(null);
    const [settings, setSettings] = useState(null);
    const [error, setError] = useState(null);
    const [permission, setPermission] = useState("unsupported");

    useEffect(() => {
        let ignore = false;
        Promise.all([getNotifications(), getAlerts(), getNotificationSettings()])
            .then(([n, a, s]) => {
                if (ignore) return;
                setInbox(n);
                setAlerts(a);
                setSettings(s);
                if (n?.unread) markNotificationsRead().catch(() => null);
            })
            .catch((err) => !ignore && setError(err.message));
        pushPermission().then((p) => !ignore && setPermission(p));
        return () => {
            ignore = true;
        };
    }, []);

    const removeAlert = async (id) => {
        try {
            await deleteAlert(id);
            setAlerts((list) => list.filter((a) => a.id !== id));
        } catch (err) {
            showToast(err.message, {type: "error"});
        }
    };

    const changeSetting = async (name) => {
        const next = {...settings, [name]: !settings[name]};
        setSettings(next);
        try {
            await putNotificationSettings(next);
        } catch (err) {
            setSettings(settings);
            showToast(err.message, {type: "error"});
        }
    };

    const turnOnPush = async () => setPermission(await enablePush(navigate));

    if (error) {
        return (
            <div className="app-page alerts-page">
                <h1 className="page-headers">Alerts</h1>
                <p className="alert-error" role="alert">{error}</p>
            </div>
        );
    }
    if (!inbox || !alerts || !settings) {
        return <div className="state-message" role="status"><div className="spinner"/>Loading your alerts…</div>;
    }

    const active = alerts.filter((a) => a.active);
    const fired = alerts.filter((a) => !a.active);

    return (
        <div className="app-page alerts-page">
            <header>
                <h1 className="page-headers">Alerts</h1>
                <p className="page-subtitle">Price alerts, earnings and dividend reminders, and a morning briefing.</p>
            </header>

            {isNative && permission !== "granted" && permission !== "unsupported" && (
                <div className="alerts-push-card">
                    <div>
                        <strong>Get them on your lock screen</strong>
                        <p>
                            {permission === "denied"
                                ? "Notifications are off for Zenith. Turn them on in iPhone Settings > Zenith > Notifications."
                                : "Allow notifications so alerts and the morning briefing reach you outside the app."}
                        </p>
                    </div>
                    {permission !== "denied" && (
                        <button type="button" className="btn btn-primary" onClick={turnOnPush}>Turn on</button>
                    )}
                </div>
            )}

            <section className="alerts-section" aria-labelledby="inbox-title">
                <h2 id="inbox-title">Notifications</h2>
                {inbox.items.length === 0 ? (
                    <p className="alerts-empty">
                        Nothing yet. Your morning briefing arrives here at 8:00 (Toronto time) on days you hold
                        something, along with alerts and reminders.
                    </p>
                ) : (
                    <ul className="alerts-list">
                        {inbox.items.map((n) => {
                            const link = safeLink(n.link);
                            const body = (
                                <>
                                    <span className="alerts-kind" aria-hidden="true">{KIND_ICONS[n.kind] ?? "🔔"}</span>
                                    <span className="alerts-text">
                                        <span className="alerts-title">
                                            {n.title}
                                            {!n.read && <span className="alerts-unread" aria-label="New"/>}
                                        </span>
                                        <span className="alerts-body">{n.body}</span>
                                        <span className="alerts-time">{timeAgo(n.created_at)}</span>
                                    </span>
                                </>
                            );
                            return (
                                <li key={n.id}>
                                    {link ? <Link to={link} className="alerts-row">{body}</Link>
                                        : <div className="alerts-row">{body}</div>}
                                </li>
                            );
                        })}
                    </ul>
                )}
            </section>

            <section className="alerts-section" aria-labelledby="my-alerts-title">
                <h2 id="my-alerts-title">Your alerts</h2>
                {alerts.length === 0 ? (
                    <p className="alerts-empty">
                        Open any stock or coin in <Link to="/search">Search</Link> and tap the bell to get notified
                        when its price crosses a level or it makes a big move.
                    </p>
                ) : (
                    <ul className="alerts-list">
                        {[...active, ...fired].map((a) => (
                            <li key={a.id} className={`alerts-row alerts-rule${a.active ? "" : " fired"}`}>
                                <span className="alerts-text">
                                    <span className="alerts-title">{a.api_id.toUpperCase()}</span>
                                    <span className="alerts-body">
                                        {a.active ? "When it " : "Fired: it "}{describe(a, currency)}
                                    </span>
                                </span>
                                <button type="button" className="alerts-delete" onClick={() => removeAlert(a.id)}
                                        aria-label={`Delete the ${a.api_id.toUpperCase()} alert`}>
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path d="M7 7l10 10M17 7L7 17" fill="none" stroke="currentColor"
                                              strokeWidth="2.2" strokeLinecap="round"/>
                                    </svg>
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            <section className="alerts-section" aria-labelledby="alert-settings-title">
                <h2 id="alert-settings-title">Notify me about</h2>
                <ul className="alerts-list">
                    {[
                        ["daily_briefing", "Morning briefing",
                            "Your overnight change, biggest movers and what's coming up, at 8:00."],
                        ["holding_events", "My holdings",
                            "Earnings and ex-dividend dates the day before, and a holding crossing its 200-day average."],
                        ...(isNative ? [["push", "On this iPhone", "Also send notifications to your phone."]] : []),
                    ].map(([name, title, hint]) => (
                        <li key={name} className="alerts-row alerts-setting">
                            <span className="alerts-text">
                                <span className="alerts-title">{title}</span>
                                <span className="alerts-body">{hint}</span>
                            </span>
                            <button type="button" role="switch" aria-checked={settings[name]} aria-label={title}
                                    className="user-toggle" onClick={() => changeSetting(name)}/>
                        </li>
                    ))}
                </ul>
            </section>
        </div>
    );
}

export default AlertsPage;
