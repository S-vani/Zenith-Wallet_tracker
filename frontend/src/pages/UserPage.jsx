import {useEffect, useRef, useState} from "react";
import {Link, useNavigate} from "react-router-dom";
import "../css/User.css"

import {putUserInfo, putUserEmail, changePassword, logoutAllDevices, deleteAccount, logout} from "../services/api.js"
import {isNative} from "../native/platform.js";
import {biometricInfo, isLockEnabled, setLockEnabled, verifyIdentity} from "../native/biometric.js";
import {lockWording} from "../native/lockRules.js";
import {useUser} from "../context/UserContext.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import usePageTitle from "../utils/usePageTitle.js";
import {showToast} from "../utils/toast.js";
import {passwordChecks, passwordRulesMet} from "../Authentication/passwordRules.js";

function UserPage() {
    usePageTitle("Account");

    const {user, setUser, error, reload} = useUser();

    if (!user) {
        return (
            <div className="app-page">
                {error ? (
                    // a failed load used to leave "Loading your account…" spinning forever
                    <div className="state-message">
                        <div className="alert-error alert-retry" role="alert">
                            <span>{error}</span>
                            <button type="button" className="btn" onClick={reload}>Try again</button>
                        </div>
                    </div>
                ) : (
                    <div className="state-message" role="status"><div className="spinner"/>Loading your account…</div>
                )}
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

    // A disabled button drops keyboard focus to <body>, and Save / Update / Delete all disable themselves while
    // they work, so these refs put focus somewhere sensible afterwards.
    const saveButtonRef = useRef(null);
    const savedMessageRef = useRef(null);
    const emailInputRef = useRef(null);
    const emailPasswordRef = useRef(null);
    const deleteButtonRef = useRef(null);
    const deletePasswordRef = useRef(null);
    // The element to focus once the next render is on screen: the target may not exist (or may still be disabled)
    // until then. Set only by handlers that also change state, so a render always follows.
    const focusAfterRender = useRef(null);
    const [saved, setSaved] = useState(false);

    useEffect(() => {
        const target = focusAfterRender.current;
        if (!target) return;
        focusAfterRender.current = null;
        target.current?.focus();
    });

    const setInformation = (info, change) => {
        setForm((prev) => ({
            ...prev,
            [info]: change
        }))
        setSaved(false);
    }

    const profileChanged = form.name.trim() !== user.name || form.currency !== user.currency;
    const emailChanged = form.email.trim().toLowerCase() !== user.email.toLowerCase();

    const handleSave = async (e) => {
        e.preventDefault();
        setSaving(true);
        setSaveError(null);
        setSaved(false);
        try {
            const updated = await putUserInfo({name: form.name.trim(), currency: form.currency});
            setUser(updated);
            // the Save button is disabled again now (nothing changed), so focus moves to the confirmation
            // (which screen readers then read) instead of falling to the page
            setSaved(true);
            focusAfterRender.current = savedMessageRef;
        } catch (err) {
            setSaveError(err.message);
            focusAfterRender.current = saveButtonRef;
        } finally {
            setSaving(false);
        }
    };

    // Undo an email edit: back to the saved address, and focus stays in the field rather than on the vanished form
    const cancelEmailChange = () => {
        setInformation("email", user.email);
        setEmailPassword("");
        setEmailError(null);
        emailInputRef.current?.focus();
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
            emailPasswordRef.current?.focus(); // usually a wrong password; the button was disabled while sending
        }
    };

    const handleLogout = () => {
        logout();
        navigate("/login", {replace: true});
    };

    // Revokes every token (a lost phone, a shared computer), then signs this device out too. It signs out every
    // other device at once, so it asks first, like the nav bar's Log out.
    const [confirmingLogoutAll, setConfirmingLogoutAll] = useState(false);
    const [loggingOutAll, setLoggingOutAll] = useState(false);
    const [logoutAllError, setLogoutAllError] = useState(null);

    const handleLogoutAll = async () => {
        setConfirmingLogoutAll(false);
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

    // Cancel (or Escape) closes the confirmation and hands focus back to the "Delete account…" button that opened it
    const cancelDelete = () => {
        setConfirmingDelete(false);
        setDeleteText("");
        setDeletePassword("");
        setDeleteError(null);
        focusAfterRender.current = deleteButtonRef;
    };

    const handleDeleteKeyDown = (e) => {
        if (e.key !== "Escape" || deleting) return;
        e.preventDefault();
        e.stopPropagation();
        cancelDelete();
    };

    const handleDelete = async (e) => {
        e.preventDefault();
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteAccount(deletePassword);
            logout(); // also turns the app's Face ID lock off (resetLockOnSignOut)
            navigate("/", {replace: true});
            showToast("Your account and all of its data have been deleted.");
        } catch (err) {
            setDeleteError(err.message);
            setDeleting(false);
            deletePasswordRef.current?.focus(); // usually a wrong password; the button was disabled while deleting
        }
    };

    const initials = user.name
        .split(" ")
        .filter(Boolean)
        .map((part) => Array.from(part)[0]) // Array.from keeps emoji whole instead of half a character
        .join("")
        .slice(0, 2)
        .toUpperCase();

    // new Date(null) is the 1970 epoch ("December 1969" west of UTC), so a missing date hides the line instead
    const joined = user.date_joined ? new Date(user.date_joined) : null;
    const memberSince = joined && !Number.isNaN(joined.getTime())
        ? joined.toLocaleDateString(undefined, {month: "long", year: "numeric"})
        : null;

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

                    <div className="user-save-row">
                        <button className="btn btn-success user-save-button" type="submit" ref={saveButtonRef}
                                disabled={!profileChanged || saving || !form.name.trim()}>
                            {saving ? "Saving…" : "Save changes"}
                        </button>
                        {/* takes focus after saving (screen readers read it then), so no toast is needed too */}
                        {saved && (
                            <p className="user-save-status" ref={savedMessageRef} tabIndex={-1}>
                                <span aria-hidden="true">✓ </span>Changes saved.
                            </p>
                        )}
                    </div>
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
                            ref={emailInputRef}
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
                                    ref={emailPasswordRef}
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
                            <div className="user-email-actions">
                                <button type="button" className="btn" onClick={cancelEmailChange}
                                        disabled={sendingVerification}>
                                    Cancel
                                </button>
                                <button
                                    className="btn btn-primary"
                                    type="submit"
                                    disabled={sendingVerification || !form.email.includes("@") || !emailPassword}
                                >
                                    {sendingVerification ? "Sending…" : "Update email"}
                                </button>
                            </div>
                        </form>
                    ) : (
                        <div className="verify-row">
                            <NoPasswordHint action="change your email"/>
                            <button type="button" className="btn" onClick={cancelEmailChange}>Cancel</button>
                        </div>
                    ))}

                    {emailError && <p className="alert-error" role="alert">{emailError}</p>}
                </div>

                <div className="user-card">
                    <div className="user-card-header">
                        <h2 className="user-card-title">Account info</h2>
                    </div>

                    {memberSince && (
                        <div className="user-info-grid">
                            <div className="user-info-row">
                                <span className="user-info-label">Member since</span>
                                <span className="user-info-value">{memberSince}</span>
                            </div>
                        </div>
                    )}

                    <nav className="user-legal-links" aria-label="Help and legal">
                        <Link to="/privacy" className="user-privacy-link">Privacy policy &amp; disclaimer</Link>
                        <Link to="/terms" className="user-privacy-link">Terms of use</Link>
                        <Link to="/support" className="user-privacy-link">Support</Link>
                    </nav>

                    <div className="user-logout-actions">
                        <button className="btn user-logout-button" onClick={handleLogout}>Log out</button>
                        <button className="btn user-logout-button" onClick={() => setConfirmingLogoutAll(true)}
                                disabled={loggingOutAll}>
                            {loggingOutAll ? "Logging out…" : "Log out of all devices"}
                        </button>
                    </div>
                    {logoutAllError && <p className="alert-error" role="alert">{logoutAllError}</p>}

                    <ConfirmDialog
                        open={confirmingLogoutAll}
                        title="Log out of all devices?"
                        message="Every device signed in to your account, including this one, will need to sign in again."
                        confirmLabel="Log out everywhere"
                        onConfirm={handleLogoutAll}
                        onCancel={() => setConfirmingLogoutAll(false)}
                    />
                </div>

                <PasswordCard hasPassword={hasPassword} email={user.email}/>

                {isNative && <SecurityCard/>}

                <div className="user-card user-danger-card">
                    <div className="user-card-header">
                        <h2 className="user-card-title">Delete account</h2>
                    </div>

                    {/* the app has no Google sign-in (it's hidden there), so it doesn't mention it */}
                    <p className="user-field-hint">
                        {isNative
                            ? "Permanently deletes your account and every transaction you've logged."
                            : "Permanently deletes your account, every transaction you've logged and any linked " +
                            "Google sign-in."}
                        {" "}This can't be undone. See our <Link to="/privacy">privacy policy</Link> for details.
                    </p>

                    {!hasPassword ? (
                        <NoPasswordHint action="delete your account"/>
                    ) : !confirmingDelete ? (
                        <button className="btn user-delete-button" ref={deleteButtonRef}
                                onClick={() => setConfirmingDelete(true)}>
                            Delete account…
                        </button>
                    ) : (
                        <form className="user-delete-confirm" onSubmit={handleDelete} onKeyDown={handleDeleteKeyDown}>
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
                                ref={deletePasswordRef}
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

// Sensitive changes ask for the current password, which Google accounts don't have until they set one.
// The app has no Google sign-in, so it doesn't name it there.
function NoPasswordHint({action}) {
    return (
        <p className="user-field-hint">
            {isNative
                ? "Your account doesn't have a password yet."
                : "You signed in with Google, so your account doesn't have a password yet."}
            {" "}To {action}, use{" "}
            <Link to="/forgot-password" className="user-inline-link">Forgot password</Link> to set one first.
        </p>
    );
}

// Change password: current, new and confirm. Other devices are signed out; this one gets a fresh token.
function PasswordCard({hasPassword, email}) {
    const empty = {current: "", next: "", confirm: ""};
    const [fields, setFields] = useState(empty);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const [changed, setChanged] = useState(false);

    // The button disables itself while saving (and stays disabled once the fields are cleared), which drops
    // keyboard focus to <body>: focus moves to the confirmation on success, back to the current password on error.
    const currentRef = useRef(null);
    const changedMessageRef = useRef(null);
    const focusAfterRender = useRef(null);

    useEffect(() => {
        const target = focusAfterRender.current;
        if (!target) return;
        focusAfterRender.current = null;
        target.current?.focus();
    });

    const setField = (name, value) => {
        setFields((prev) => ({...prev, [name]: value}));
        setError(null);
        setChanged(false);
    };

    const mismatch = fields.confirm !== "" && fields.next !== fields.confirm;
    const rulesMet = passwordRulesMet(fields.next, email);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        setError(null);
        setChanged(false);
        try {
            await changePassword(fields.current, fields.next);
            setFields(empty);
            setChanged(true);
            focusAfterRender.current = changedMessageRef;
        } catch (err) {
            setError(err.message);
            focusAfterRender.current = currentRef; // usually a wrong current password
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
                        <input id="password-current" ref={currentRef} className="user-field-input" type="password"
                               value={fields.current} onChange={(e) => setField("current", e.target.value)}
                               autoComplete="current-password" required/>
                    </div>
                    <div className="user-field">
                        <label className="user-field-label" htmlFor="password-new">New password</label>
                        <input id="password-new" className="user-field-input" type="password"
                               value={fields.next} onChange={(e) => setField("next", e.target.value)}
                               autoComplete="new-password" maxLength={128} aria-describedby="password-new-rules"
                               required/>
                        <PasswordChecklist password={fields.next} email={email}/>
                    </div>
                    <div className="user-field">
                        <label className="user-field-label" htmlFor="password-confirm">Confirm new password</label>
                        <input id="password-confirm" className="user-field-input" type="password"
                               value={fields.confirm} onChange={(e) => setField("confirm", e.target.value)}
                               autoComplete="new-password" maxLength={128} required/>
                        {mismatch && <span className="user-field-hint error-hint">The passwords don't match.</span>}
                    </div>

                    {error && <p className="alert-error" role="alert">{error}</p>}

                    <div className="user-save-row">
                        <button className="btn btn-primary user-save-button" type="submit"
                                disabled={saving || !fields.current || !rulesMet || mismatch
                                    || fields.next !== fields.confirm}>
                            {saving ? "Changing…" : "Change password"}
                        </button>
                        {/* takes focus after the change (screen readers read it then), so no toast is needed too */}
                        {changed && (
                            <p className="user-save-status" ref={changedMessageRef} tabIndex={-1}>
                                <span aria-hidden="true">✓ </span>Password changed. Your other devices have been
                                signed out.
                            </p>
                        )}
                    </div>
                </form>
            )}
        </div>
    );
}

// Live checklist under the new password, the same as the sign-up form's (SignupForm's PasswordChecklist). The live
// region is always in the page but stays empty until the user starts typing, so it doesn't nag up front.
function PasswordChecklist({password, email}) {
    return (
        <div id="password-new-rules" className="password-rules" aria-live="polite">
            {password && (
                <>
                    <ul className="password-rules-list">
                        {passwordChecks(password, email).map((check) => (
                            <li key={check.id} className={check.met ? "met" : undefined}>
                                <span className="password-rules-icon" aria-hidden="true">{check.met ? "✓" : "○"}</span>
                                {check.label}
                                <span className="visually-hidden">{check.met ? " (done)" : " (not yet)"}</span>
                            </li>
                        ))}
                    </ul>
                    {/* only the server has the common-password list, so the checklist doesn't tick it off */}
                    <p className="password-rules-note">Very common passwords are also refused.</p>
                </>
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
    const words = lockWording(info.label);

    useEffect(() => {
        biometricInfo().then(setInfo);
        isLockEnabled().then((on) => setEnabled(on === true));
    }, []);

    const toggle = async () => {
        setBusy(true);
        setError(null);
        try {
            // both ways: someone holding an unlocked phone shouldn't be able to switch the lock off
            await verifyIdentity(enabled ? words.turnOffReason : words.turnOnReason);
            await setLockEnabled(!enabled);
            setEnabled(!enabled);
            showToast(enabled ? words.turnedOff : words.turnedOn);
        } catch {
            setError(words.notConfirmed);
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
                    <span className="user-field-label">{words.title}</span>
                    <p className="user-field-hint">
                        {info.available
                            ? words.hint
                            : `Set up ${info.label} or a passcode in your iPhone's Settings to use this.`}
                    </p>
                </div>
                <button type="button" role="switch" aria-checked={enabled} aria-label={words.title}
                        className="user-toggle" onClick={toggle} disabled={busy || !info.available}/>
            </div>
            {error && <p className="alert-error" role="alert">{error}</p>}
        </div>
    );
}

export default UserPage;
