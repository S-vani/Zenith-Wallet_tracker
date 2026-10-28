import {useEffect, useState} from "react";

// Money that rolls to its new value like an odometer: each digit is a strip of 0-9 moved with a transform (cheap, on
// the GPU), so the text and its width never change mid-animation. Screen readers get the plain text once; the
// moving digits are hidden from them. Under prefers-reduced-motion the global rule makes the change instant.
// Digits are keyed from the right, so the cents stay in place when the amount gains a digit.
function RollingNumber({text}) {
    // first render at 0, then roll up to the real digits
    const [ready, setReady] = useState(false);
    useEffect(() => {
        const frame = requestAnimationFrame(() => setReady(true));
        return () => cancelAnimationFrame(frame);
    }, []);

    const chars = [...text];
    return (
        <span className="rolling">
            <span className="visually-hidden">{text}</span>
            <span className="rolling-digits" aria-hidden="true">
                {chars.map((ch, i) => {
                    const fromRight = chars.length - i;
                    if (!/\d/.test(ch)) return <span key={fromRight} className="rolling-static">{ch}</span>;
                    return (
                        <span key={fromRight} className="rolling-col"
                              style={{"--d": ready ? Number(ch) : 0, "--i": fromRight}}>
                            <span className="rolling-strip">
                                {"0123456789".split("").map((d) => <span key={d}>{d}</span>)}
                            </span>
                        </span>
                    );
                })}
            </span>
        </span>
    );
}

export default RollingNumber;
