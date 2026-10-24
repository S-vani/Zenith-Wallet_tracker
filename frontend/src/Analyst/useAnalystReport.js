import {useCallback, useEffect, useState} from "react";
import {getAnalystReport} from "../services/api.js";
import {showToast} from "../utils/toast.js";
import {analystRequestKey, clockOffset, createLatestRequestTracker, fetchLatest} from "./analystUtils.js";

// Loads the analyst report for one asset and handles manual refreshes.
// Stale responses can't leak in: every new request aborts the previous one, a response that arrives anyway is
// dropped by fetchLatest(), and results are stored with the key of the asset they belong to and only shown while
// that key is still the selected asset.
export default function useAnalystReport({symbol, type, coinId}) {
    const key = analystRequestKey({symbol, type, coinId});
    const [tracker] = useState(createLatestRequestTracker);
    const [result, setResult] = useState(null); // {key, report, error, offset}
    const [refreshing, setRefreshing] = useState(null); // key of the asset being refreshed
    const [refreshError, setRefreshError] = useState(null); // {key, message}

    const load = useCallback((refresh = false) => fetchLatest(
        tracker,
        (signal) => getAnalystReport({symbol, type, coinId, refresh}, {signal}),
    ), [tracker, symbol, type, coinId]);

    useEffect(() => {
        load().then((res) => {
            if (res.status === "ok") setResult({key, report: res.data, error: null, offset: clockOffset(res.data)});
            else if (res.status === "error") setResult({key, report: null, error: res.error.message});
        });
        return () => tracker.cancel();
    }, [load, key, tracker]);

    // Retry after an error: back to the loading skeleton, then load again
    const retry = useCallback(async () => {
        setResult(null);
        const res = await load();
        if (res.status === "ok") setResult({key, report: res.data, error: null, offset: clockOffset(res.data)});
        else if (res.status === "error") setResult({key, report: null, error: res.error.message});
    }, [load, key]);

    // Manual refresh keeps the current report on screen; a failure (e.g. 429) is shown next to the button
    const refresh = useCallback(async () => {
        setRefreshing(key);
        setRefreshError(null);
        const res = await load(true);
        // "superseded": the asset changed or the panel closed, so the response is dropped
        if (res.status === "ok") {
            setResult({key, report: res.data, error: null, offset: clockOffset(res.data)});
        } else if (res.status === "error" && res.error.status === 429) {
            // refreshed too recently (maybe in another tab): say so briefly and show the newest saved report,
            // whose refresh_available_at drives the button's countdown
            showToast(res.error.message, {type: "error"});
            const latest = await load(false);
            if (latest.status === "ok") setResult({key, report: latest.data, error: null, offset: clockOffset(latest.data)});
        } else if (res.status === "error") {
            setRefreshError({key, message: res.error.message, status: res.error.status});
        }
        setRefreshing((current) => (current === key ? null : current));
    }, [load, key]);

    const current = result?.key === key ? result : null;

    return {
        loading: !current,
        report: current?.report ?? null,
        error: current?.error ?? null,
        clockOffset: current?.offset ?? 0, // ms the device clock runs ahead of the server (see clockOffset)
        refreshing: refreshing === key,
        refreshError: refreshError?.key === key ? refreshError : null,
        retry,
        refresh,
    };
}
