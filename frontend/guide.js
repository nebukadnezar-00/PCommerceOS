// ------------------------------------------------------------ Rehber (first-run guide)
// Five animated steps: Sitelerin · API anahtarı · İlk arama · Takip ve sepet · Siparişlerin. Opens once by itself
// after the boot screen on a fresh install; afterwards the "Yardıma mı ihtiyacın var?" button (a little robot,
// left of the settings icon) opens it again, always from the first step; the progress bar's segments jump
// to any step. A step shows "✓ Tamam" from what the user actually did (/api/guide reads it from the data).
// "Göster" closes the dialog and lights up the place to use, with a one-line hint; its "Tamam" (or Esc, or closing
// the AI settings) brings the guide back on the same step. Uses app.js's window.commerceGuide hooks (setView, showPanel,
// openDrawer, narrow) and aisettings.js's openAiSettings.
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const realFetch = window.fetch.bind(window);
  async function api(path, opts = {}) {
    const res = await realFetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
                                        body: opts.body ? JSON.stringify(opts.body) : undefined });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }
  const hooks = () => window.commerceGuide || {};
  const narrow = () => matchMedia("(max-width: 999px)").matches;

  // ---------------------------------------------------------- the steps
  const STEPS = {
    sites: {
      title: "Sitelerin", icon: "grid",
      text: "Sık alışveriş yaptığın mağazalar logo olarak dizilir. Logoya dokununca site açılır; ⊕ ile yenisini ekler, sürükleyerek sıralarsın.",
      hint: "Logoya dokunup siteyi aç. + ile yeni site ekle, sürükleyerek sırala.",
      art: `<div class="gd-tiles">${["#f27a1a", "#ff6000", "#232f3e", "#7a1fa2"].map((c, i) => `<span style="--c:${c};--i:${i}"></span>`).join("")}<span class="gd-plus">+</span></div>`,
      show: () => {
        if (narrow()) { hooks().openDrawer?.("sites"); return "#sites-panel"; }
        return ".sites-bar";
      },
    },
    ai: {
      title: "Yapay zekâ anahtarı", icon: "key",
      text: "Hızlı arama anahtarsız çalışır. Derin ara (internetin tamamında yapay zekâyla arama) için bir API anahtarı gerekir; Ayarlar'dan istediğin sağlayıcıyı seçip anahtarını girersin.",
      art: `<div class="gd-lock"><svg viewBox="0 0 64 64" width="64" height="64" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><rect class="gd-lock-body" x="16" y="28" width="32" height="26" rx="5"/><path class="gd-lock-arc" d="M23 28v-7a9 9 0 0 1 18 0v7"/><circle cx="32" cy="41" r="3"/></svg><svg class="gd-key" viewBox="0 0 64 24" width="64" height="24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><circle cx="9" cy="12" r="6"/><path d="M15 12h34M41 12v6M47 12v5"/></svg><span class="gd-pill">Derin ara</span></div>`,
      show: () => {
        window.openAiSettings?.();
        const d = $("#ai-dialog");                       // watch [open]: also covers Esc and the backdrop
        if (d) new MutationObserver((_, mo) => { if (!d.open) { mo.disconnect(); resume(); } })
          .observe(d, { attributes: true, attributeFilter: ["open"] });
        return null;
      },
    },
    search: {
      title: "İlk aramanı yap", icon: "search",
      text: "Ürün adını yaz; mağazaların fiyatları en ucuzdan sıralanır. Hızlı arama token harcamaz.",
      hint: "Buraya bir ürün yaz ve Enter'a bas.",
      art: `<div class="gd-search"><div class="gd-box">⌕ <span class="gd-type">airpods pro 2</span></div><div class="gd-cards"><span class="best">Mağaza A · 7.499 TL</span><span>Mağaza B · 7.650 TL</span><span>Mağaza C · 7.820 TL</span></div></div>`,
      show: () => {
        if (narrow()) hooks().setView?.("search");
        setTimeout(() => $("#q")?.focus({ preventScroll: true }), 250);
        return ".search-card";
      },
    },
    track: {
      title: "Takip et, sepete ekle", icon: "bell",
      text: "Bir aramada 🔔 ile fiyatı takibe al: düşünce haber verir. Sepete eklediklerini mağazalara bölerek en ucuza alırsın.",
      hint: "Bir aramadan sonra 🔔 Takip et ya da Sepete ekle'ye bas; ürünler burada toplanır.",
      art: `<div class="gd-track"><svg class="gd-bell" viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg><svg class="gd-line" viewBox="0 0 120 50" width="120" height="50" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path pathLength="100" d="M4 10 L30 16 L52 12 L76 30 L98 26 L116 42"/></svg><span class="gd-tag">−%12</span></div>`,
      show: () => {
        hooks().showPanel?.("track");
        return "#tracking-card";
      },
    },
    mail: {
      title: "Siparişlerin", icon: "mail",
      text: "Gmail'i bağlarsan siparişlerin ve kargoların mağaza e-postalarından kendiliğinden gelir. E-postalar yalnızca okunur, token harcanmaz.",
      hint: "E-posta bağla ile Gmail'ini ekle; siparişler burada listelenir.",
      art: `<div class="gd-mail"><svg viewBox="0 0 64 48" width="64" height="48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"><rect x="4" y="12" width="56" height="32" rx="4"/><path class="gd-flap" d="M4 14 L32 32 L60 14"/></svg><div class="gd-ship"><i></i><span>🚚</span></div></div>`,
      show: () => { hooks().showPanel?.("orders"); return "#orders-card"; },
    },
  };

  // ---------------------------------------------------------- styles
  document.head.insertAdjacentHTML("beforeend", `<style>
.gd-chip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border));
  background: var(--accent-bg); color: var(--accent); border-radius: 999px; padding: 3px 10px 3px 6px; font: inherit; font-size: 12.5px;
  font-weight: 600; cursor: pointer; white-space: nowrap; }
.gd-chip:hover { background: color-mix(in srgb, var(--accent) 18%, transparent); }
/* the little robot: bobs, blinks, its antenna light pulses */
.gd-bot { flex: none; animation: gd-bob 2.4s ease-in-out infinite; }
.gd-bot .eye { animation: gd-blink 4s infinite; transform-origin: center; transform-box: fill-box; }
.gd-bot .tip { animation: gd-tip 1.2s ease-in-out infinite; }
@keyframes gd-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-1.5px); } }
@keyframes gd-blink { 0%, 92%, 100% { transform: scaleY(1); } 95% { transform: scaleY(.1); } }
@keyframes gd-tip { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }
.gd-dialog { border: 1px solid var(--border); border-radius: 16px; padding: 0; width: min(520px, calc(100vw - 32px));
  background: var(--surface); color: var(--text); box-shadow: 0 20px 50px rgba(0,0,0,.3); }
.gd-dialog::backdrop { background: rgba(10, 12, 16, .5); }
.gd-dialog[open] { animation: gd-in .28s ease-out; }
@keyframes gd-in { from { opacity: 0; transform: translateY(12px) scale(.98); } to { opacity: 1; transform: none; } }
.gd-in { padding: 16px 18px 18px; }
.gd-top { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
.gd-top .gd-x { margin-left: auto; border: 0; background: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 6px; }
.gd-bar { display: flex; gap: 6px; margin-bottom: 14px; }
.gd-bar button { flex: 1; height: 16px; border: 0; padding: 0; background: none; cursor: pointer; display: flex; align-items: center; }
.gd-bar button::before { content: ""; flex: 1; height: 4px; border-radius: 4px; background: var(--border); transition: background .3s, height .15s; }
.gd-bar button:hover::before { height: 6px; }
.gd-bar button.cur::before { background: var(--accent); height: 6px; }
.gd-bar button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
.gd-stage { height: 132px; border-radius: 12px; background: var(--surface-2); display: flex; align-items: center; justify-content: center; overflow: hidden; color: var(--accent); }
.gd-dialog h3 { margin: 14px 0 4px; font-size: 17px; display: flex; align-items: center; gap: 8px; }
.gd-done { font-size: 11.5px; font-weight: 600; color: var(--up); background: var(--up-bg); border-radius: 999px; padding: 2px 8px; }
.gd-dialog p { margin: 0 0 14px; font-size: 13.5px; color: var(--muted); line-height: 1.5; }
.gd-actions { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.gd-actions span { display: flex; gap: 8px; margin-left: auto; }
.gd-btn { border: 1px solid var(--border); background: var(--surface-2); color: var(--text); border-radius: 8px; padding: 7px 14px; font: inherit; font-size: 13px; cursor: pointer; }
.gd-btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-text); }
.gd-btn[disabled] { visibility: hidden; }
/* step art */
.gd-tiles { display: flex; gap: 10px; align-items: center; }
.gd-tiles span { width: 38px; height: 38px; border-radius: 10px; background: var(--c); opacity: 0; animation: gd-drop 3.2s ease-out infinite; animation-delay: calc(var(--i) * .18s); }
.gd-tiles .gd-plus { --i: 4; background: none; border: 2px dashed var(--accent); color: var(--accent); display: grid; place-items: center; font-weight: 700; font-size: 20px; }
@keyframes gd-drop { 0% { opacity: 0; transform: translateY(-18px); } 15%, 85% { opacity: 1; transform: none; } 100% { opacity: 0; } }
.gd-lock { display: flex; align-items: center; gap: 4px; position: relative; color: var(--muted); }
.gd-key { color: var(--accent); animation: gd-key 3.2s ease-in-out infinite; }
.gd-lock-arc { animation: gd-arc 3.2s ease-in-out infinite; transform-origin: 41px 28px; }
.gd-lock svg:first-child { animation: gd-lockc 3.2s infinite; }
.gd-pill { margin-left: 12px; font-size: 12px; font-weight: 600; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); animation: gd-pill 3.2s infinite; }
@keyframes gd-key { 0%, 10% { transform: translateX(40px); opacity: 0; } 35%, 100% { transform: translateX(0); opacity: 1; } }
@keyframes gd-arc { 0%, 45% { transform: none; } 60%, 100% { transform: translateY(-6px); } }
@keyframes gd-lockc { 0%, 50% { color: var(--muted); } 60%, 100% { color: var(--up); } }
@keyframes gd-pill { 0%, 60% { color: var(--muted); background: none; } 70%, 100% { color: var(--accent-text); background: var(--accent); border-color: var(--accent); } }
.gd-search { display: grid; gap: 10px; justify-items: center; color: var(--text); }
.gd-box { width: 230px; border: 1px solid var(--border); background: var(--surface); border-radius: 8px; padding: 7px 10px; font-size: 13px; }
.gd-type { display: inline-block; overflow: hidden; white-space: nowrap; vertical-align: bottom; width: 0; animation: gd-type 3.2s steps(13) infinite; }
@keyframes gd-type { 0%, 10% { width: 0; } 45%, 100% { width: 13ch; } }
.gd-cards { display: flex; gap: 6px; }
.gd-cards span { font-size: 11px; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); opacity: 0; animation: gd-drop 3.2s ease-out infinite; animation-delay: .9s; }
.gd-cards span:nth-child(2) { animation-delay: 1.05s; } .gd-cards span:nth-child(3) { animation-delay: 1.2s; }
.gd-cards span { white-space: nowrap; }
@media (max-width: 420px) { .gd-cards span:nth-child(3) { display: none; } }
.gd-cards .best { color: var(--up); border-color: color-mix(in srgb, var(--up) 50%, var(--border)); background: var(--up-bg); }
.gd-track { display: flex; align-items: center; gap: 14px; }
.gd-bell { transform-origin: 50% 10%; animation: gd-ring 3.2s ease-in-out infinite; }
@keyframes gd-ring { 0%, 8% { transform: rotate(0); } 12% { transform: rotate(16deg); } 18% { transform: rotate(-14deg); } 24% { transform: rotate(10deg); } 30%, 100% { transform: rotate(0); } }
.gd-line path { stroke: var(--up); stroke-dasharray: 100; stroke-dashoffset: 100; animation: gd-draw 3.2s ease-out infinite; }
@keyframes gd-draw { 0%, 15% { stroke-dashoffset: 100; } 65%, 100% { stroke-dashoffset: 0; } }
.gd-tag { font-size: 12px; font-weight: 700; color: var(--up); background: var(--up-bg); padding: 4px 8px; border-radius: 8px; opacity: 0; animation: gd-pop 3.2s infinite; }
@keyframes gd-pop { 0%, 60% { opacity: 0; transform: scale(.6); } 70%, 100% { opacity: 1; transform: none; } }
.gd-mail { display: grid; gap: 12px; justify-items: center; }
.gd-flap { transform-origin: 32px 14px; animation: gd-flap 3.2s ease-in-out infinite; }
@keyframes gd-flap { 0%, 15% { transform: none; } 35%, 100% { transform: scaleY(-1); } }
.gd-ship { position: relative; width: 170px; height: 6px; border-radius: 6px; background: var(--border); }
.gd-ship i { position: absolute; inset: 0 auto 0 0; border-radius: 6px; background: var(--up); width: 0; animation: gd-fill 3.2s ease-in-out infinite; }
.gd-ship span { position: absolute; top: -18px; left: 0; font-size: 16px; animation: gd-truck 3.2s ease-in-out infinite; }
@keyframes gd-fill { 0%, 30% { width: 0; } 85%, 100% { width: 100%; } }
@keyframes gd-truck { 0%, 30% { left: -6px; } 85%, 100% { left: calc(100% - 14px); } }
/* "Göster": spotlight + hint */
.gd-spot { position: fixed; z-index: 90; border-radius: 14px; pointer-events: none; border: 2px solid var(--accent);
  box-shadow: 0 0 0 9999px rgba(10, 12, 16, .45); animation: gd-spot 1.6s ease-out infinite; transition: all .2s; }
@keyframes gd-spot { 0% { outline: 0 solid color-mix(in srgb, var(--accent) 55%, transparent); } 100% { outline: 12px solid transparent; } }
.gd-hint { position: fixed; z-index: 91; max-width: min(340px, calc(100vw - 32px)); background: var(--surface); color: var(--text);
  border: 1px solid var(--accent); border-radius: 10px; padding: 10px 12px; font-size: 13px; box-shadow: 0 10px 30px rgba(0,0,0,.25); }
.gd-hint button { margin-left: 8px; }
@media (max-width: 640px) {
  .gd-dialog { margin: auto 0 0; width: 100%; max-width: 100%; border-radius: 16px 16px 0 0; padding-bottom: env(safe-area-inset-bottom); }
  /* phone: only the robot */
  .gd-chip { padding: 0; width: 32px; height: 32px; justify-content: center; border-radius: 50%; }
  .gd-chip .gd-label { display: none; }
  /* room for it: a slightly smaller brand and heartbeat, which keeps its own width again */
  .topbar { gap: 10px; }
  .brand { font-size: 15px; gap: 8px; }
  .status-wrap { flex: none; }
  .status .pulse { width: 28px; }
  .top-right { gap: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  .gd-dialog *, .gd-chip, .gd-chip *, .gd-spot { animation: none !important; }
  .gd-tiles span, .gd-cards span, .gd-tag { opacity: 1; } .gd-type { width: 13ch; } .gd-line path { stroke-dashoffset: 0; }
  .gd-ship i { width: 70%; } .gd-ship span { left: 60%; }
}
</style>`);

  // ---------------------------------------------------------- state
  let st = null;               // /api/guide
  let cur = 0;                 // step shown in the dialog
  const order = () => (st ? st.steps.map((s) => s.id) : Object.keys(STEPS));
  const doneCount = () => (st ? st.steps.filter((s) => s.done).length : 0);
  const isDone = (id) => !!st?.steps.find((s) => s.id === id)?.done;

  async function refresh() {
    try { st = await api("/api/guide"); } catch (_) { return; }
    if (dialog.open) render();
  }

  // ---------------------------------------------------------- header chip
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "gd-chip";
  chip.addEventListener("click", () => open());
  // on the right of the header, just left of the settings icon
  const gear = document.querySelector(".top-right [data-open-settings]");
  if (gear) gear.before(chip); else document.querySelector(".top-right")?.prepend(chip);
  chip.title = "Yardıma mı ihtiyacın var?";
  chip.setAttribute("aria-label", "Yardıma mı ihtiyacın var? Rehberi aç");
  chip.innerHTML = `<svg class="gd-bot" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle class="tip" cx="12" cy="3" r="1.2" fill="currentColor" stroke="none"/><path d="M12 4.5V7"/>
      <rect x="5" y="7" width="14" height="11" rx="3.5"/><path d="M3 11.5v3M21 11.5v3"/>
      <circle class="eye" cx="9.3" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle class="eye" cx="14.7" cy="12" r="1.3" fill="currentColor" stroke="none"/>
      <path d="M10 15.3h4"/></svg><span class="gd-label">Yardıma mı ihtiyacın var?</span>`;

  // ---------------------------------------------------------- dialog
  const dialog = document.createElement("dialog");
  dialog.className = "gd-dialog";
  dialog.setAttribute("aria-label", "CommerceOS rehberi");
  document.body.append(dialog);
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });   // backdrop

  function open(at) {
    cur = typeof at === "number" ? at : 0;              // from the first step, unless resuming
    render();
    if (!dialog.open) dialog.showModal();
    if (st && !st.seen) { st.seen = true; api("/api/guide", { method: "PUT", body: { seen: true } }).catch(() => {}); }
  }

  function render() {
    const ids = order(), id = ids[cur], s = STEPS[id];
    const last = cur === ids.length - 1;
    dialog.innerHTML = `<div class="gd-in">
      <div class="gd-top"><span>Adım ${cur + 1} / ${ids.length}</span>
        <button class="gd-x" type="button" aria-label="Kapat" data-gd="close">✕</button></div>
      <div class="gd-bar">${ids.map((x, i) => `<button type="button" data-gd="go" data-i="${i}" class="${i === cur ? "cur" : ""}" aria-label="${i + 1}. adım: ${esc(STEPS[x].title)}${isDone(x) ? " (tamam)" : ""}"${i === cur ? ' aria-current="step"' : ""}></button>`).join("")}</div>
      <div class="gd-stage" aria-hidden="true">${s.art}</div>
      <h3>${esc(s.title)}${isDone(id) ? ` <span class="gd-done">✓ Tamam</span>` : ""}</h3>
      <p>${esc(s.text)}</p>
      <div class="gd-actions">
        <button class="gd-btn" type="button" data-gd="back" ${cur === 0 ? "disabled" : ""}>Geri</button>
        <span><button class="gd-btn" type="button" data-gd="next">${last ? "Bitir" : isDone(id) ? "Sonraki" : "Atla"}</button>
          <button class="gd-btn primary" type="button" data-gd="show">${id === "ai" ? "Ayarları aç →" : "Göster →"}</button></span>
      </div></div>`;
  }

  dialog.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-gd]");
    if (!b) return;
    const act = b.dataset.gd, ids = order();
    if (act === "close") dialog.close();
    else if (act === "back") { cur = Math.max(0, cur - 1); render(); }
    else if (act === "go") { cur = Number(b.dataset.i); render(); dialog.querySelector(`[data-i="${cur}"]`)?.focus(); }
    else if (act === "next") { if (cur === ids.length - 1) dialog.close(); else { cur += 1; render(); } }
    else if (act === "show") show(ids[cur]);
  });

  // ---------------------------------------------------------- "Göster"
  let spot = null, hint = null, target = null;
  function resume() {                                    // back to the step "Göster" left from
    const at = cur;
    refresh().then(() => open(at));
  }
  function clearSpot() {
    spot?.remove(); hint?.remove();
    spot = hint = target = null;
    removeEventListener("scroll", place, true);
    removeEventListener("resize", place);
  }
  function place() {
    if (!target || !document.body.contains(target)) { clearSpot(); return; }
    const r = target.getBoundingClientRect(), pad = 6;
    Object.assign(spot.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
    const below = r.bottom + 12 + hint.offsetHeight < innerHeight;
    const left = Math.min(Math.max(16, r.left), innerWidth - hint.offsetWidth - 16);
    Object.assign(hint.style, { left: `${left}px`, top: below ? `${r.bottom + 12}px` : `${Math.max(16, r.top - hint.offsetHeight - 12)}px` });
  }
  function show(id) {
    dialog.close();
    clearSpot();
    const sel = STEPS[id].show();
    if (!sel) return;
    setTimeout(() => {                                   // after the tab switch / drawer opening
      target = $(sel);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      spot = document.createElement("div");
      spot.className = "gd-spot";
      hint = document.createElement("div");
      hint.className = "gd-hint";
      hint.setAttribute("role", "status");
      hint.innerHTML = `${esc(STEPS[id].hint)} <button class="gd-btn primary" type="button">Tamam</button>`;
      hint.querySelector("button").addEventListener("click", async () => {
        clearSpot();
        if (id === "sites" && !isDone("sites")) {
          try { st = await api("/api/guide", { method: "PUT", body: { done: "sites" } }); } catch (_) { /* later */ }
        }
        resume();
      });
      document.body.append(spot, hint);
      place();
      setTimeout(place, 450);                            // after the smooth scroll
      addEventListener("scroll", place, true);
      addEventListener("resize", place);
    }, 260);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && spot) { clearSpot(); resume(); } });
  dialog.addEventListener("keydown", (e) => {                 // ← → move between the steps
    if (e.target.closest("input, textarea")) return;
    const n = order().length;
    if (e.key === "ArrowRight" && cur < n - 1) { cur += 1; render(); }
    else if (e.key === "ArrowLeft" && cur > 0) { cur -= 1; render(); }
  });
  document.addEventListener("pointerdown", (e) => { if (spot && !hint.contains(e.target)) setTimeout(clearSpot, 0); }, true);

  // ---------------------------------------------------------- keep the count current
  // after any change the app makes (a search, a tracked product, a Gmail connection…) ask again, once
  let timer = null;
  window.fetch = async (...args) => {
    const res = await realFetch(...args);
    const url = String(args[0]?.url || args[0] || "");
    if (url.startsWith("/api/") && !/^\/api\/(guide|status|glance)\b/.test(url)) {
      clearTimeout(timer);
      timer = setTimeout(refresh, 700);
    }
    return res;
  };
  addEventListener("ai-settings-changed", refresh);

  // ---------------------------------------------------------- first run
  async function start() {
    await refresh();
    // only for someone new: whoever has searched before only gets the chip
    if (st && !st.seen && !isDone("search")) open();
  }
  const bootEl = document.getElementById("boot");
  if (bootEl && !bootEl.classList.contains("done")) addEventListener("commerce-boot-done", start, { once: true });
  else start();
  window.openGuide = open;
})();
