(() => {
    const GITHUB_URL = "https://github.com/OpenCureLabs/OpenCureLabs";
    const LOGO_URL = "https://pub.opencurelabs.ai/assets/logo-symbol.svg";
    const FOOTER_LINKS = [
        ["github", "GitHub", GITHUB_URL, true],
        ["x", "X @shoneanstey", "https://x.com/shoneanstey", true],
        ["data", "Data API", "/data", false],
        ["contribute", "Contribute", "/contribute", false],
        ["about", "About", "/about", false],
        ["feed", "Feed", "/", false],
    ];
    const NAV_LINKS = [
        ["feed", "Feed", "/"],
        ["data", "Data", "/data"],
        ["contribute", "Contribute", "/contribute"],
        ["about", "About", "/about"],
    ];
    const GITHUB_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>';

    function pageName() {
        return document.body?.dataset.page || "feed";
    }

    function renderHeader() {
        const activePage = pageName();
        const header = document.createElement("header");
        header.className = "site-header";
        const nav = NAV_LINKS.map(([key, label, href]) => {
            const active = key === activePage ? ' class="active"' : "";
            return `<a href="${href}"${active}>${label}</a>`;
        }).join("");
        const status = activePage === "feed"
            ? '<span class="header-updated" id="last-updated">Fetching latest results...</span>'
            : "";

        header.innerHTML = `
            <a class="site-brand" href="/">
                <img src="${LOGO_URL}" alt="OpenCure Labs" />
                <h1>OpenCure Labs</h1>
            </a>
            <nav class="nav-links" id="nav-links">
                ${nav}
                <a class="gh-badge-mobile" href="${GITHUB_URL}" target="_blank" rel="noopener">${GITHUB_ICON} GitHub</a>
            </nav>
            <a class="gh-badge" href="${GITHUB_URL}" target="_blank" rel="noopener" title="Star us on GitHub">${GITHUB_ICON} GitHub</a>
            ${status}
            <button class="hamburger" type="button" aria-label="Toggle menu" aria-controls="nav-links" aria-expanded="false">☰</button>
        `;

        const button = header.querySelector(".hamburger");
        const links = header.querySelector("#nav-links");
        button?.addEventListener("click", () => {
            const isOpen = links.classList.toggle("open");
            button.setAttribute("aria-expanded", String(isOpen));
        });
        document.body.prepend(header);
    }

    function renderFooter() {
        const footer = document.createElement("footer");
        footer.className = "site-footer";
        const currentPage = pageName();
        const links = FOOTER_LINKS
            .filter(([key]) => key !== currentPage)
            .map(([, label, href, external]) => {
                const attrs = external ? ' target="_blank" rel="noopener"' : "";
                return `<a href="${href}"${attrs}>${label}</a>`;
            })
            .join("");
        footer.innerHTML = `
            <div class="footer-inner">
                <div class="footer-links">${links}</div>
                <div class="footer-disclaimer">
                    All artifacts are AI-generated and should be independently validated.
                    Each includes Ed25519 signatures and provenance metadata for inspection.
                </div>
                <div style="font-size:0.72rem;color:var(--muted)">© 2026 OpenCure Labs · Open source under MIT License · Made with care in Vancouver, Canada</div>
            </div>
        `;
        document.body.appendChild(footer);
    }

    function initShell() {
        renderHeader();
        renderFooter();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initShell, { once: true });
    } else {
        initShell();
    }
})();
