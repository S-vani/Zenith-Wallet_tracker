import {getPublicConfig} from "../services/api.js";
import {levelFromServer, lowerMotionLevel} from "./motionLevel.js";

// The server's effects kill switch (FX_LEVEL in .env, GET /config): "lite" or "off" calms every device without a new
// release. The last answer is kept, so the next start applies it before anything heavy runs, even offline.
const KEY = "fxServer";

// Applies the last known setting (at startup).
export function applyStoredKillSwitch() {
    try {
        const saved = localStorage.getItem(KEY);
        if (saved) lowerMotionLevel(levelFromServer(saved));
    } catch {
        // no storage: the next answer from the server still applies
    }
}

// Asks the server (in the background) and applies the answer; failures change nothing.
export function refreshKillSwitch() {
    getPublicConfig()
        .then(({fx_level: level}) => {
            try {
                localStorage.setItem(KEY, level);
            } catch {
                // fine
            }
            lowerMotionLevel(levelFromServer(level));
        })
        .catch(() => null);
}
