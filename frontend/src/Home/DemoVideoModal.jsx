import {useCallback, useEffect, useId, useRef, useState} from "react";
import {Link} from "react-router-dom";

import "../css/DemoVideo.css";

// files live in frontend/public/demo/
const VIDEO_SRC = "/demo/zenith-demo.mp4";
const POSTER_SRC = "/demo/zenith-demo-poster.jpg";

// keep in sync with the demoOut animation in DemoVideo.css
const CLOSE_ANIMATION_MS = 180;

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Rendered only while open, so the video (and its poster) isn't downloaded until someone asks for it.
function DemoVideoModal({onClose, loggedIn, returnFocusRef}) {
    const titleId = useId();
    const captionId = useId();
    const videoRef = useRef(null);
    const closeButtonRef = useRef(null);
    const closeTimer = useRef(null);
    const scrollToFeatures = useRef(false);
    const [closing, setClosing] = useState(false);
    const [failed, setFailed] = useState(false);

    const requestClose = useCallback(() => {
        const video = videoRef.current;
        if (video) {
            video.pause();
            video.currentTime = 0;
        }
        // no exit animation to wait for when motion is reduced
        if (prefersReducedMotion()) {
            onClose();
            return;
        }
        setClosing(true);
        clearTimeout(closeTimer.current);
        closeTimer.current = setTimeout(onClose, CLOSE_ANIMATION_MS);
    }, [onClose]);

    useEffect(() => () => clearTimeout(closeTimer.current), []);

    // move focus into the dialog, and give it back to the button that opened it
    useEffect(() => {
        const trigger = returnFocusRef?.current;
        closeButtonRef.current?.focus();
        // preventScroll: "Explore features" scrolls the page down, don't jump back to the hero
        return () => trigger?.focus({preventScroll: true});
    }, [returnFocusRef]);

    // the click that opened the modal counts as a user gesture, so most browsers allow playing with sound.
    // If one refuses, the controls are already showing and the user can press play themselves.
    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;
        video.play()?.catch(() => null);
        return () => {
            video.pause();
            video.currentTime = 0;
        };
    }, []);

    // close with Escape
    useEffect(() => {
        const onKey = (e) => e.key === "Escape" && requestClose();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [requestClose]);

    // stop the page behind the modal from scrolling
    useEffect(() => {
        const previous = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        return () => {
            document.body.style.overflow = previous;
            // "Explore features": scroll only after the page is unlocked, so the scroll isn't blocked or cut short
            if (scrollToFeatures.current) document.getElementById("features")?.scrollIntoView();
        };
    }, []);

    const exploreFeatures = (e) => {
        e.preventDefault();
        scrollToFeatures.current = true;
        requestClose();
    };

    return (
        <div className={`demo-overlay${closing ? " is-closing" : ""}`}
             onMouseDown={(e) => e.target === e.currentTarget && requestClose()}>
            <div className="demo-box" role="dialog" aria-modal="true" aria-labelledby={titleId}
                 aria-describedby={captionId}>
                <div className="demo-header">
                    <div className="demo-heading">
                        <h2 id={titleId}>See Zenith in action</h2>
                        <p id={captionId} className="demo-caption">
                            A quick tour: your dashboard and holdings, logging a buy, and the Market Analyst's
                            outlook for any stock or coin.
                        </p>
                    </div>
                    <button type="button" ref={closeButtonRef} className="demo-close-button"
                            onClick={requestClose} aria-label="Close video">
                        <img src="/assets/close.png" alt=""/>
                    </button>
                </div>

                <div className="demo-frame">
                    {failed ? (
                        <div className="demo-error" role="alert">
                            <strong>The demo video couldn't be loaded right now.</strong>
                            <span>You can still take a look at what Zenith does below.</span>
                            <a href="#features" className="btn" onClick={exploreFeatures}>Explore features</a>
                        </div>
                    ) : (
                        <video
                            ref={videoRef}
                            className="demo-video"
                            src={VIDEO_SRC}
                            poster={POSTER_SRC}
                            controls
                            playsInline
                            preload="auto"
                            onError={() => setFailed(true)}
                        />
                    )}
                </div>

                <div className="demo-footer">
                    <span className="demo-footer-note">
                        {loggedIn ? "Your portfolio is one click away." : "Free to use. No credit card needed."}
                    </span>
                    <Link to={loggedIn ? "/dashboard" : "/signup"} className="auth-btn signup-btn">
                        {loggedIn ? "Go to your dashboard" : "Create free account"}
                    </Link>
                </div>
            </div>
        </div>
    );
}

export default DemoVideoModal;
