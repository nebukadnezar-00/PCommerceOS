// Shared theme (dark / light). The same file lives in every OS Suite app — keep the copies identical.
//
// Contract: the choice is the cookie `os_suite_theme=dark|light`. Cookies ignore ports, so every app
// on this device read the same value; no cookie = dark. Each page also has an
// inline <head> snippet that sets <html data-theme> before the first paint (no flash), and this
// script then wires every [data-theme-toggle] button, switches instantly, keeps open pages in
// sync when they come back to the front, and fires a `themechange` event on document.
(() => {
  const NAME = "os_suite_theme", YEAR = 365 * 24 * 3600;
  const root = document.documentElement;

  const read = () => (document.cookie.match(/(?:^|;\s*)os_suite_theme=(dark|light)/) || [])[1] || "dark";
  const current = () => (root.dataset.theme === "light" ? "light" : "dark");

  function paintChrome() {
    const bg = getComputedStyle(document.body || root).backgroundColor;
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) { meta = document.createElement("meta"); meta.name = "theme-color"; document.head.append(meta); }
    if (bg) meta.content = bg;
    document.querySelectorAll("[data-theme-toggle]").forEach((b) => {
      const dark = current() === "dark";
      b.setAttribute("aria-label", dark ? "Açık temaya geç" : "Koyu temaya geç");
      b.title = dark ? "Açık tema" : "Koyu tema";
    });
  }

  function apply(theme) {
    root.dataset.theme = theme;
    paintChrome();
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  }

  function set(theme) {
    document.cookie = `${NAME}=${theme}; path=/; max-age=${YEAR}; SameSite=Lax`;
    if (theme !== current()) apply(theme);  // instant: no page transition effect
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest?.("[data-theme-toggle]");
    if (b) set(current() === "dark" ? "light" : "dark");
  });
  // another page of the system may have changed it while this one was in the background
  const sync = () => { if (read() !== current()) apply(read()); };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(); });
  addEventListener("focus", sync);
  addEventListener("pageshow", sync);

  if (root.dataset.theme !== read()) root.dataset.theme = read();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paintChrome);
  else paintChrome();

  window.osSuiteTheme = { get: current, set };
})();
