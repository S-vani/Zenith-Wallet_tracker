import {useEffect} from "react";

export default function usePageTitle(title) {
    useEffect(() => {
        document.title = title ? `${title} · Zenith Wallet Tracker` : "Zenith Wallet Tracker";
    }, [title]);
}
