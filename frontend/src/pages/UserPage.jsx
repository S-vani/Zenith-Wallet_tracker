import {useEffect, useState} from "react";
import {Link, useNavigate} from "react-router-dom";
import "../css/User.css"

import {putUserInfo, putUserEmail, changePassword, logoutAllDevices, deleteAccount, logout} from "../services/api.js"
import {isNative} from "../native/platform.js";
import {biometricInfo, isLockEnabled, setLockEnabled, verifyIdentity} from "../native/biometric.js";
import {useUser} from "../context/UserContext.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import {showToast} from "../utils/toast.js";

function UserPage() {
    usePageTitle("Account");

    const {user, setUser} = useUser();

    if (!user) {
        return (
            <div className="app-page">
                <div className="state-message"><div className="spinner"/>Loading your account…</div>
            </div>
        );
    }

    return <UserSettings user={user} setUser={setUser}/>;
}

// Rendered once the user is loaded, so the form can start from their saved values
function UserSettings({user, setUser}) {
    const navigate = useNavigate();
    const [form, setForm] = useState({name: user.name, currency: user.currency, email: user.email});
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [sendingVerification, setSendingVerification] = useState(false);
    const [emailError, setEmailError] = useState(null);
    const [emailPassword, setEmailPassword] = useState("");
    // Accounts made with Google have no password of their own until they set one through "Forgot password"
    const hasPassword = user.hasPassword !== false;

    const setInformation = (info, change) => {
        setForm((prev) => ({
            ...prev,
            [info]: change
        }))
    }

    const profileChanged = form.name.trim() !== user.name || form.currency !== user.currency;
    const emailChanged = form.email.trim().toLowerCase() !== user.email.toLowerCase();

    const handleSave = async (e) => {
        e.preventDefault();
        setSaving(true);
        setSaveError(null);
        try {
            const updated = await putUserInfo({name: form.name.trim(), currency: form.currency});
            setUser(updated);
            showToast("Changes saved");
        } catch (err) {
            setSaveError(err.message);
        } finally {
            setSaving(false);
        }
    };

    // Changing the email unverifies the account, so the user is signed out until they confirm the new address
    const handleEmailChange = async (e) => {
        e.preventDefault();
        setSendingVerification(true);
        setEmailError(null);
        try {
            await putUserEmail(form.email, emailPassword)
            logout();
            navigate("/login", {
                replace: true,
                state: {notice: `We sent a verification link to ${form.email.trim()}. Verify it, then log in with your new email.`}
            });
        } catch (err) {
            setEmailError(err.message);
            setSendingVerification(false);
        }
    };

    const handleLogout = () => {
        logout();
        navigate("/login", {replace: true});
    };

    // Revokes every token (a lost phone, a shared computer), then signs this device out too
    const [loggingOutAll, setLoggingOutAll] = useState(false);
    const [logoutAllError, setLogoutAllError] = useState(null);

    const handleLogoutAll = async () => {
        setLoggingOutAll(true);
        setLogoutAllError(null);
        try {
            await logoutAllDevices();
            logout();
            navigate("/login", {replace: true, state: {notice: "You've been logged out of all devices."}});
        } catch (err) {
            setLogoutAllError(err.message);
            setLoggingOutAll(false);
        }
    };

    // Deleting needs a second, deliberate step: open the confirmation, type DELETE and enter the password
    const [confirmingDelete, setConfirmingDelete] = useState(false);
    const [deleteText, setDeleteText] = useState("");
    const [deletePassword, setDeletePassword] = useState("");
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState(null);

    const cancelDelete = () => {
        setConfirmingDelete(false);
        setDeleteText("");
        setDeletePassword("");
        setDeleteError(null);
    };

    const handleDelete = async (e) => {
        e.preventDefault();
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteAccount(deletePassword);
            if (isNative) await setLockEnabled(false).catch(() => null); // app: no Face ID lock left behind
            logout();
            navigate("/", {replace: true});
            showToast("Your account and all of its data have been deleted.");
        } catch (err) {
            setDeleteError(err.message);
            setDeleting(false);
        }
    };

    const initials = user.name
        .split(" ")
        .filter(Boolean)
        .map((part) => Array.from(part)[0]) // Array.from keeps emoji whole instead of half a character
        .join("")
        .slice(0, 2)
        .toUpperCase();

    const memberSince = new Date(user.date_joined).toLocaleDateString(undefined, {month: "long", year: "numeric"});

    return (
        <div className="user-page-wrapper">
            <div className="user-page">
                <div className="user-header">
                    <div className="user-avatar" aria-hidden="true">{initials}</div>
                    <div className="user-header-info">
                        <h1 className="user-header-name">{user.name}</h1>
                        <span className="user-header-sub">Account settings</span>
                    </div>
                </div>

                <form className="user-card" onSubmit={handleSave}>
                    <div className="user-card-header">
                        <h2 className="user-card-title">Profile</h2>
                    </div>

                    <div className="user-field">
                        <label className="user-field-label" htmlFor="user-name">Name</label>
                        <input
                            id="user-name"
                            className="user-field-input"
                            value={form.name}
                            onChange={(e) => setInformation("name", e.target.value)}
                            placeholder="Your name"
                            autoComplete="name"
                            maxLength={100}
                            required
                        />
                        {!form.name.trim() && <span className="user-field-hint error-hint">Name can't be empty.</span>}
                    </div>

                    <div className="user-field">
                        <label className="user-field-label" htmlFor="user-currency">Currency</label>
                        <select
                            id="user-currency"
                            className="user-field-select"
                            value={form.currency}
                            onChange={(e) => setInformation("currency", e.target.value)}
                        >
                            <option value="CAD">CAD — Canadian Dollar</option>
                            <option value="USD">USD — US Dollar</option>
                            <option value="EUR">EUR — Euro</option>
                        </select>
                        <span className="user-field-hint">All prices and totals are shown in this currency.</span>
                    </div>

                    {saveError && <p className="alert-error" role="alert">{saveError}</p>}

                    <div className="user-divider"/>

                    <button className="btn btn-success user-save-button" type="submit"
                            disabled={!profileChanged || saving || !form.name.trim()}>
                        {saving ? "Saving…" : "Save changes"}
                    </button>
                </form>

                <div className="user-card">
                    <div className="user-card-header">
                        <h2 className="user-card-title">Email</h2>
                        {emailChanged ? (
                            <span className="verify-badge unverified">Not saved</span>
                        ) : (
                            <span className={`verify-badge ${user.isVerified ? "verified" : "unverified"}`}>
                                {user.isVerified ? "Verified" : "Unverified"}
                            </span>
                        )}
                    </div>

                    <div className="user-field">
                        <label className="user-field-label" htmlFor="user-email">Email address</label>
                        <input
                            id="user-email"
                            className="user-field-input"
                            type="email"
                            value={form.email}
                            onChange={(e) => {
                                setInformation("email", e.target.value);
                                setEmailError(null);
                            }}
                            placeholder="you@example.com"
                            autoComplete="email"
                        />
                    </div>

                    {emailChanged && (hasPassword ? (
                        <form className="verify-row" onSubmit={handleEmailChange}>
                            <p className="user-field-hint">
                                We'll send a verification link to the new address and let your old one know.
                                You'll be signed out on every device until you confirm it.
                            </p>
                            <div className="user-field user-field-full">
                                <label className="user-field-label" htmlFor="email-password">Current password</label>
                                <input
                                    id="email-password"
                                    className="user-field-input"
                                    type="password"
                                    value={emailPassword}
                                    onChange={(e) => {
                                        setEmailPassword(e.target.value);
                                        setEmailError(null);
                                    }}
                                    autoComplete="current-password"
                                    required
                                />
                            </div>
                            <button
                                className="btn btn-primary"
                                type="submit"
                                disabled={sendingVerification || !form.email.includes("@") || !emailPassword}
                            >
                                {sendingVerification ? "Sending…" : "Update email"}
                            </button>
                        </form>
                    ) : (
                        <NoPasswordHint action="change your email"/>
                    ))}

                    {emailError && <p className="alert-error" role="alert">{emailError}</p>}
                </div>

                <div className="user-card">
                    <div className="user-card-header">
                        <h2 className="user-card-title">Account info</h2>
                    </div>

                    <div className="user-info-grid">
                        <div className="user-info-row">
                            <span className="user-info-label">Member since</span>
                            <span className="user-info-value">{memberSince}</span>
                        </div>
                    </div>

                    <Link to="/privacy" className="user-privacy-link">Privacy policy &amp; disclaimer</Link>

                    <div className="user-logout-actions">
                        <button className="btn user-logout-button" onClick={handleLogout}>Log out</button>
                        <button className="btn user-logout-button" onClick={handleLogoutAll} disabled={loggingOutAll}>
                            {loggingOutAll ? "Logging out…" : "Log out of all devices"}
                        </button>
                    </div>
                    {logoutAllError && <p className="alert-error" role="alert">{logoutAllError}</p>}
                </div>

                <PasswordCard hasPassword={hasPassword}/>

                {isNative && <SecurityCard/>}

                <div className="user-card user-danger-card">
                    <div className="user-card-header">
                        <h2 className="user-card-title">Delete account</h2>
                    </div>

                    <p className="user-field-hint">
                        Permanently deletes your account, every transaction you've logged and any linked Google
                        sign-in. This can't be undone. See our <Link to="/privacy">privacy policy</Link> for details.
                    </p>

                    {!hasPassword ? (
                        <NoPasswordHint action="delete your account"/>
                    ) : !confirmingDelete ? (
                        <button className="btn user-delete-button" onClick={() => setConfirmingDelete(true)}>
                            Delete account…
                        </button>
                    ) : (
                        <form className="user-delete-confirm" onSubmit={handleDelete}>
                            <label className="user-field-label" htmlFor="delete-confirm">
                                Type <strong>DELETE</strong> to confirm
                            </label>
                            <input
                                id="delete-confirm"
                                className="user-field-input"
                                value={deleteText}
                                onChange={(e) => setDeleteText(e.target.value)}
                                autoComplete="off"
                                autoCapitalize="characters"
                                spellCheck={false}
                                autoFocus
                            />

                            <label className="user-field-label" htmlFor="delete-password">Current password</label>
                            <input
                                id="delete-password"
                                className="user-field-input"
                                type="password"
                                value={deletePassword}
                                onChange={(e) => setDeletePassword(e.target.value)}
                                autoComplete="current-password"
                            />

                            {deleteError && <p className="alert-error" role="alert">{deleteError}</p>}

                            <div className="user-delete-actions">
                                <button type="button" className="btn" onClick={cancelDelete} disabled={deleting}>
                                    Cancel
                                </button>
                                <button type="submit" className="btn user-delete-submit"
                                        disabled={deleteText.trim() !== "DELETE" || !deletePassword || deleting}>
                                    {deleting ? "Deleting…" : "Delete my account"}
                                </button>
                            </div>
                        </form>
                    )}
                </div>
            </div>
        </div>
    )
}

// Sensitive changes ask for the current password, which Google accounts don't have until they set one
function NoPasswordHint({action}) {
    return (
        <p className="user-field-hint">
            You signed in with Google, so your account doesn't have a password yet. To {action}, use{" "}
            <Link to="/forgot-password" className="user-inline-link">Forgot password</Link> to set one first.
        </p>
    );
}

// Change password: current, new and confirm. Other devices are signed out; this one gets a fresh token.
function PasswordCard({hasPassword}) {
    const empty = {current: "", next: "", confirm: ""};
    const [fields, setFields] = useState(empty);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const setField = (name, value) => {
        setFields((prev) => ({...prev, [name]: value}));
        setError(null);
    };

    const mismatch = fields.confirm !== "" && fields.next !== fields.confirm;
    const tooShort = fields.next !== "" && fields.next.length < 8;

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        try {
            await changePassword(fields.current, fields.next);
            setFields(empty);
            showToast("Password changed. Your other devices have been signed out.");
        } catch (err) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="user-card">
            <div className="user-card-header">
                <h2 className="user-card-title">Password</h2>
            </div>

            {!hasPassword ? (
                <NoPasswordHint action="change your password"/>
            ) : (
                <form className="user-password-form" onSubmit={handleSubmit}>
                    <div className="user-field">
                        <label className="user-field-label" htmlFor="password-current">Current password</label>
                        <input id="password-current" className="user-field-input" type="password"
                               value={fields.current} onChange={(e) => setField("current", e.target.value)}
                               autoComplete="current-password" required/>
                    </div>
                    <div className="user-field">
                        <label className="user-field-label" htmlFor="password-new">New password</label>
                        <input id="password-new" className="user-field-input" type="password"
                               value={fields.next} onChange={(e) => setField("next", e.target.value)}
                               autoComplete="new-password" maxLength={128} required/>
                        {tooShort && <span className="user-field-hint error-hint">At least 8 characters.</span>}
                    </div>
                    <div className="user-field">
                        <label className="user-field-label" htmlFor="password-confirm">Confirm new password</label>
                        <input id="password-confirm" className="user-field-input" type="password"
                               value={fields.confirm} onChange={(e) => setField("confirm", e.target.value)}
                               autoComplete="new-password" maxLength={128} required/>
                        {mismatch && <span className="user-field-hint error-hint">The passwords don't match.</span>}
                    </div>

                    {error && <p className="alert-error" role="alert">{error}</p>}

                    <button className="btn btn-primary user-save-button" type="submit"
                            disabled={saving || !fields.current || !fields.next || tooShort || mismatch
                                || fields.next !== fields.confirm}>
                        {saving ? "Changing…" : "Change password"}
                    </button>
                </form>
            )}
        </div>
    );
}

// App only: turn the Face ID lock on or off. Turning it on asks for Face ID once, so it can't be switched on
// by someone whose face won't open it.
function SecurityCard() {
    const [info, setInfo] = useState({available: false, label: "Face ID"});
    const [enabled, setEnabled] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        biometricInfo().then(setInfo);
        isLockEnabled().then((on) => setEnabled(on === true));
    }, []);

    const toggle = async () => {
        setBusy(true);
        setError(null);
        try {
            // both ways: someone holding an unlocked phone shouldn't be able to switch the lock off
            await verifyIdentity(enabled ? `Turn off the ${info.label} lock` : `Turn on ${info.label} for Zenith`);
            await setLockEnabled(!enabled);
            setEnabled(!enabled);
            showToast(enabled ? `${info.label} lock turned off` : `${info.label} lock turned on`);
        } catch {
            setError(`${info.label} wasn't confirmed, so nothing changed.`);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="user-card">
            <div className="user-card-header">
                <h2 className="user-card-title">Security</h2>
            </div>
            <div className="user-toggle-row">
                <div>
                    <span className="user-field-label">Require {info.label}</span>
                    <p className="user-field-hint">
                        {info.available
                            ? `Lock Zenith whenever you leave the app. Open it again with ${info.label} or your passcode.`
                            : `Set up ${info.label} or a passcode in your iPhone's Settings to use this.`}
                    </p>
                </div>
                <button type="button" role="switch" aria-checked={enabled} aria-label={`Require ${info.label}`}
                        className="user-toggle" onClick={toggle} disabled={busy || !info.available}/>
            </div>
            {error && <p className="alert-error" role="alert">{error}</p>}
        </div>
    );
}

export default UserPage;
