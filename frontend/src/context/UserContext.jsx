import {createContext, useCallback, useContext, useEffect, useState} from "react";
import {getUser} from "../services/api.js";
import {normalizeCurrency} from "../utils/format.js";

const UserContext = createContext(null);

// Loads the signed in user once and shares it with every page instead of each page fetching it again.
// `currency` stays null until the user is known: guessing CAD showed USD/EUR users amounts labelled CA$ (for good,
// if /user failed), so money is shown as "—" until then (formatMoney(value, null)).
export function UserProvider({children}) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // every state change here happens once getUser() answers (none while the effect below runs)
    const fetchUser = useCallback(() => {
        // a 401 is handled globally by the api layer
        return getUser()
            .then((data) => {
                setUser(data);
                setError(null);
            })
            .catch((err) => {
                // a failed refresh keeps the user already loaded; only a first load without one is an error
                setError(err?.message || "Couldn't load your account. Please try again.");
            })
            .finally(() => setLoading(false));
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
            {children}
        </UserContext.Provider>
    );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useUser() {
    return useContext(UserContext);
}
