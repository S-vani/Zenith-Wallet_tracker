import {useState, useEffect} from "react";
import "../css/User.css"

import {getUser, putUserInfo} from "../services/api.js"

function UserPage() {
    const [userInformation, setUserInformation] = useState({
        "name": "",
        "email": "",
        "isVerified": false,
        "currency": "",
        "dateJoined": ""
    })
    const [sendingVerification, setSendingVerification] = useState(false);
    const [verificationSent, setVerificationSent] = useState(false);

    const handleSave = async () => {
        const userinfo = await putUserInfo(userInformation)
        console.log("Saving profile:", userInformation);
        console.log("Saving profile:", userinfo);
    };

    const handleVerify = async () => {
        setSendingVerification(true);
        try {
            // TODO: wire up to send-verification-email endpoint
            await new Promise((resolve) => setTimeout(resolve, 800));
            setVerificationSent(true);
        } finally {
            setSendingVerification(false);
        }
    };

    const setInformation = (info, change) => {
        setUserInformation((prev) => ({
            ...prev,
            info: change
        }))
    }


    useEffect(() => {
        async function getUserInformation() {
            const info = await getUser();

            const formattedDate = new Date(info.date_joined).toLocaleDateString(
                "en-US",
                {
                    month: "long",
                    year: "numeric",
                }
            );

            const formattedInfo = {
                name: info.name,
                email: info.email,
                isVerified: false,
                currency: info.currency,
                dateJoined: formattedDate,
            };

            setUserInformation(formattedInfo)
        }

        getUserInformation()
    }, [])

    return (
        <div className="user-page-wrapper">
            <button onClick={() => console.log(userInformation)}>asdsads</button>
            <div className="user-page">
                <div className="user-header">
                    <div className="user-avatar">
                        {userInformation.name
                            .split(" ")
                            .map((part) => part[0])
                            .join("")
                            .slice(0, 2)
                            .toUpperCase()}
                    </div>
                    <div className="user-header-info">
                        <span className="user-header-name">{userInformation.name}</span>
                        <span className="user-header-sub">Account settings</span>
                    </div>
                </div>

                <div className="user-card">
                    <div className="user-card-header">
                        <span className="user-card-title">Profile</span>
                    </div>

                    <div className="user-field">
                        <label className="user-field-label">Name</label>
                        <input
                            className="user-field-input"
                            value={userInformation.name}
                            onChange={(e) => setInformation("name", e.target.value)}
                            placeholder="Your name"
                        />
                    </div>

                    <div className="user-field">
                        <label className="user-field-label">Email</label>
                        <div className="user-email-row">
                            <input
                                className="user-field-input"
                                value={userInformation.email}
                                onChange={(e) => {
                                    setInformation("email", e.target.value);
                                    setInformation("isVerified", false);
                                    setVerificationSent(false);
                                }}
                                placeholder="you@example.com"
                            />
                            <span
                                className={`verify-badge ${userInformation.isVerified ? "verified" : "unverified"}`}
                            >
                                {userInformation.isVerified ? "Verified" : "Unverified"}
                            </span>
                        </div>

                        {!userInformation.isVerified && (
                            <div className="verify-row">
                                {verificationSent ? (
                                    <span className="verify-sent-text">
                                        Verification email sent — check your inbox.
                                    </span>
                                ) : (
                                    <button
                                        className="verify-button"
                                        onClick={handleVerify}
                                        disabled={sendingVerification}
                                    >
                                        {sendingVerification ? "Sending..." : "Verify email"}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>

                    <div className="user-divider"/>

                    <button className="user-save-button" onClick={handleSave}>
                        Save changes
                    </button>
                </div>

                <div className="user-card">
                    <div className="user-card-header">
                        <span className="user-card-title">Account info</span>
                    </div>

                    <div className="user-info-grid">
                        <div className="user-info-row">
                            <span className="user-info-label">Member since</span>
                            <span className="user-info-value">March 2024</span>
                        </div>
                        <div className="divider"/>
                        <div className="user-info-row">
                            <span className="user-info-label">Portfolio value</span>
                            <span className="user-info-value">$—</span>
                        </div>
                        <div className="divider"/>
                        <div className="user-info-row">
                            <span className="user-info-label">Last login</span>
                            <span className="user-info-value">—</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default UserPage;
