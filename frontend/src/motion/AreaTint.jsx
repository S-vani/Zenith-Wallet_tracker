import {useLayoutEffect} from "react";
import {useLocation} from "react-router-dom";
import {areaFor, setArea} from "./mood.js";

// Sets <html data-area> from the route, which tints the page's ambient light (design/areas.css). Renders nothing.
function AreaTint() {
    const {pathname} = useLocation();
    useLayoutEffect(() => setArea(areaFor(pathname)), [pathname]);
    return null;
}

export default AreaTint;
