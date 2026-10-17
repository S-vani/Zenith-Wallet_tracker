import {useState} from "react";
import {Link, useNavigate} from "react-router-dom";
import "../css/User.css"

import {putUserInfo, putUserEmail, deleteAccount, logout} from "../services/api.js"
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
    const handleEmailChange = async () => {
        setSendingVerification(true);
        setEmailError(null);
        try {
            await putUserEmail(form.email)
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

    // Deleting needs a second, deliberate step: open the confirmation, then type DELETE
    const [confirmingDelete, setConfirmingDelete] = useState(false);
    const [deleteText, setDeleteText] = useState("");
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState(null);

    const cancelDelete = () => {
        setConfirmingDelete(false);
        setDeleteText("");
        setDeleteError(null);
    };

    const handleDelete = async (e) => {
        e.preventDefault();
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteAccount();
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

                    {emailChanged && (
                        <div className="verify-row">
                            <p className="user-field-hint">
                                We'll send a verification link to the new address. You'll be signed out until you
                                confirm it.
                            </p>
                            <button
                                className="btn btn-primary"
                                onClick={handleEmailChange}
                                disabled={sendingVerification || !form.email.includes("@")}
                            >
                                {sendingVerification ? "Sending…" : "Update email"}
                            </button>
                        </div>
                    )}

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

                    <button className="btn user-logout-button" onClick={handleLogout}>Log out</button>
                </div>

                <div className="user-card user-danger-card">
                    <div className="user-card-header">
                        <h2 className="user-card-title">Delete account</h2>
                    </div>

                    <p className="user-field-hint">
                        Permanently deletes your account, every transaction you've logged and any linked Google
                        sign-in. This can't be undone. See our <Link to="/privacy">privacy policy</Link> for details.
                    </p>

                    {!confirmingDelete ? (
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

                            {deleteError && <p className="alert-error" role="alert">{deleteError}</p>}

                            <div className="user-delete-actions">
                                <button type="button" className="btn" onClick={cancelDelete} disabled={deleting}>
                                    Cancel
                                </button>
                                <button type="submit" className="btn user-delete-submit"
                                        disabled={deleteText.trim() !== "DELETE" || deleting}>
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

export default UserPage;
