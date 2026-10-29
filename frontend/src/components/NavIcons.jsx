// One consistent line-icon set for the nav (same 24x24 grid and stroke), replacing the mixed-size PNGs

function Icon({children}) {
    return (
        <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {children}
        </svg>
    );
}

// Magnifying glass (Search).
export function SearchIcon() {
    return (
        <Icon>
            <circle cx="11" cy="11" r="7"/>
            <line x1="20.5" y1="20.5" x2="16" y2="16"/>
        </Icon>
    );
}

// House (Dashboard).
export function HomeIcon() {
    return (
        <Icon>
            <path d="M3.5 10.5 12 3.5l8.5 7"/>
            <path d="M5.5 9v10.5a1 1 0 0 0 1 1H10v-6h4v6h3.5a1 1 0 0 0 1-1V9"/>
        </Icon>
    );
}

// Receipt (Transactions).
export function TransactionsIcon() {
    return (
        <Icon>
            <path d="M14 3H6.5a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/>
            <path d="M14 3v5h5"/>
            <path d="M14 11.5h-3a1.25 1.25 0 0 0 0 2.5h2a1.25 1.25 0 0 1 0 2.5h-3"/>
            <line x1="12" y1="10.5" x2="12" y2="17.5"/>
        </Icon>
    );
}

// Bar chart (Holdings).
export function HoldingsIcon() {
    return (
        <Icon>
            <line x1="3" y1="20.5" x2="21" y2="20.5"/>
            <rect x="4" y="12" width="3.5" height="6" rx="0.75"/>
            <rect x="10" y="7" width="3.5" height="11" rx="0.75"/>
            <rect x="16" y="3.5" width="3.5" height="14.5" rx="0.75"/>
        </Icon>
    );
}

// Person (Account).
export function ProfileIcon() {
    return (
        <Icon>
            <circle cx="12" cy="8" r="4"/>
            <path d="M4.5 20.5c1.2-3.6 4.2-5.5 7.5-5.5s6.3 1.9 7.5 5.5"/>
        </Icon>
    );
}

// Arrow out of a door (Log out).
export function LogoutIcon() {
    return (
        <Icon>
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
        </Icon>
    );
}
