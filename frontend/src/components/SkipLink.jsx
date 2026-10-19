// The first thing Tab reaches on every page: jumps past the nav bar / brand links to the page's <main>
// (id="main-content", tabIndex -1 so it can take focus). Hidden until focused (Global.css).
// Focus is moved by hand instead of following the #hash, which would add "#main-content" to the address and a
// history entry.
function SkipLink() {
    const skip = (e) => {
        const target = document.getElementById("main-content") ?? document.querySelector("main");
        if (!target) return;
        e.preventDefault();
        if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus(); // scrolls it into view if needed; the next Tab goes to its first link or field
    };

    return <a href="#main-content" className="skip-link" onClick={skip}>Skip to main content</a>;
}

export default SkipLink;
