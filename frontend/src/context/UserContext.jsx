import {createContext, Fragment, useCallback, useContext, useEffect, useRef, useState} from "react";
import {useNavigate} from "react-router-dom";
import {getToken, getUser, TOKEN_KEY} from "../services/api.js";
import {normalizeCurrency} from "../utils/format.js";
import {isNative} from "../native/platform.js";

const UserContext = createContext(null);

// Loads the signed in user once and shares it with every page instead of each page fetching it again.
// `currency` stays null until the user is known: guessing CAD showed USD/EUR users amounts labelled CA$ (for good,
// if /user failed), so money is shown as "—" until then (formatMoney(value, null)).
export function UserProvider({children}) {
    const navigate = useNavigate();
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    // bumped when another tab signs in, so every page below remounts and fetches again with the new token
    const [generation, setGeneration] = useState(0);
    // only the newest /user answer counts: one started before a sign in elsewhere would bring back the old account
    const latestRequest = useRef(0);

    // every state change here happens once getUser() answers (none while the effect below runs)
    const fetchUser = useCallback(() => {
        const request = ++latestRequest.current;
        // a 401 is handled globally by the api layer
        return getUser()
            .then((data) => {
                if (request !== latestRequest.current) return;
                setUser(data);
                setError(null);
            })
            .catch((err) => {
                if (request !== latestRequest.current) return;
                // a failed refresh keeps the user already loaded; only a first load without one is an error
                setError(err?.message || "Couldn't load your account. Please try again.");
            })
            .finally(() => {
                if (request === latestRequest.current) setLoading(false);
            });
    }, []);

    // "Try again" after a failed load: back to loading, then fetch again
    const reload = useCallback(() => {
        setLoading(true);
        setError(null);
        return fetchUser();
    }, [fetchUser]);

    useEffect(() => {
        fetchUser();

        // settings may have changed in another tab, so refresh when the user comes back to this one
        window.addEventListener("focus", fetchUser);
        return () => window.removeEventListener("focus", fetchUser);
    }, [fetchUser]);

    // Another tab logged out or signed in (perhaps as someone else): without this, this tab kept the old name while
    // its requests already used the other account's token. Web only: the iOS app has a single web view.
    // `storage` events only reach *other* tabs and this handler never writes the token, so tabs can't ping-pong.
    useEffect(() => {
        if (isNative) return;
        let lastToken = getToken();

        const onStorage = (e) => {
            // key is null when another tab cleared all of localStorage
            if (e.storageArea !== localStorage || (e.key !== null && e.key !== TOKEN_KEY)) return;
            const token = getToken();
            if (token === lastToken) return;
            lastToken = token;

            if (!token) {
                navigate("/login", {replace: true, state: {notice: "You logged out in another tab."}});
                return;
            }
            setUser(null);
            setLoading(true);
            setError(null);
            setGeneration((n) => n + 1);
            fetchUser();
        };

        window.addEventListener("storage", onStorage);
        return () => window.removeEventListener("storage", onStorage);
    }, [fetchUser, navigate]);

    const value = {
        user,
        setUser,
        currency: user ? normalizeCurrency(user.currency) : null,
        loading: loading && !user,
        error: user ? null : error,
        reload,
    };

    return (
        <UserContext.Provider value={value}>
            <Fragment key={generation}>{children}</Fragment>
        </UserContext.Provider>
    );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useUser() {
    return useContext(UserContext);
}
