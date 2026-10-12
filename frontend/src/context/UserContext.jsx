import {createContext, useContext, useEffect, useState} from "react";
import {getUser} from "../services/api.js";
import {normalizeCurrency} from "../utils/format.js";

const UserContext = createContext(null);

// Loads the signed in user once and shares it with every page instead of each page fetching it again
export function UserProvider({children}) {
    const [user, setUser] = useState(null);

    useEffect(() => {
        // a 401 is handled globally by the api layer
        const load = () => getUser().then(setUser).catch(() => null);
        load();

        // settings may have changed in another tab, so refresh when the user comes back to this one
        window.addEventListener("focus", load);
        return () => window.removeEventListener("focus", load);
    }, []);

    return (
        <UserContext.Provider value={{user, setUser, currency: normalizeCurrency(user?.currency)}}>
            {children}
        </UserContext.Provider>
    );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useUser() {
    return useContext(UserContext);
}
