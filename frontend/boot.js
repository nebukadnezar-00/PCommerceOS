// ------------------------------------------------------------ boot screen
// FinanceOS's boot screen (FinanceOS/frontend/js/boot.js) without ES modules: app.js is a plain
// script, so the two calls it needs are on window.commerceBoot.
// Shown once per tab (a reload skips it, see the <head> script). Each log line is tied to a real
// loading step and the ring fills as steps finish. Click or Esc skips it.
(() => {
  const MIN_MS = 1200;      // long enough to read the log even when data arrives instantly
  const MAX_MS = 10000;     // never hold the page back longer than this
  const started = performance.now();
  const boot = document.getElementById("boot");
  const active = boot && !document.documentElement.classList.contains("booted");
  const steps = active ? [...boot.querySelectorAll("[data-step]")] : [];
  let done = 0, closed = false;

  steps.forEach((li) => li.classList.add("wait"));

  function progress() {
    const pct = Math.round(done / steps.length * 100);
    document.getElementById("boot-arc").style.strokeDashoffset = String(100 - pct);
    document.getElementById("boot-pct").firstChild.textContent = String(pct);
    boot.setAttribute("aria-valuenow", String(pct));
  }

  function mark(step, ok) {
    if (!active) return;
    const li = boot.querySelector(`[data-step="${step}"]`);
    if (!li || !li.classList.contains("wait")) return;
    li.classList.remove("wait");
    li.classList.add(ok ? "ok" : "fail");
    li.querySelector(".boot-res").textContent = ok ? "OK" : "HATA";
    if (!ok) boot.classList.add("has-fail");
    done += 1;
    progress();
  }

  // Pass a loading promise through, marking its line; a resolved `false` also counts as a failure.
  function track(step, promise) {
    if (!active) return promise;
    return promise.then((v) => { mark(step, v !== false); return v; },
                        (e) => { mark(step, false); throw e; });
  }

  function close() {
    if (closed) return;
    closed = true;
    try { sessionStorage.setItem("booted", "1"); } catch (_) {}
    boot.classList.add("done");
    setTimeout(() => { boot.remove(); window.dispatchEvent(new Event("commerce-boot-done")); }, 450);   // guide.js waits for it
  }

  async function finish() {
    if (!active || closed) return;
    const wait = MIN_MS - (performance.now() - started);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    if (closed) return;                         // skipped (click / Esc) while waiting
    boot.classList.add("locked");
    document.getElementById("boot-label").textContent = "HAZIR";
    document.getElementById("boot-ready").textContent = "SİSTEM HAZIR";
    setTimeout(close, 350);
  }

  if (active) {
    boot.addEventListener("click", close);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !closed) { e.stopImmediatePropagation(); close(); } }, true);
    setTimeout(close, MAX_MS);
  } else {
    boot?.remove();
  }

  window.commerceBoot = { track, mark, finish, active };
})();
