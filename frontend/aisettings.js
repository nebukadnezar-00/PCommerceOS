// ------------------------------------------------------------ Ayarlar → Yapay zekâ (shared)
// ONE FILE, COPIED AS-IS into every OS Suite app, next to providers.py.
// A plain script: it builds its own dialog and styles from the module's colour variables, and opens
// from any element with [data-open-settings]. Primary + backup AI provider: pick a provider, paste
// its key, test (no tokens), save. Keys are write-only — the server only returns the last 4
// characters — and the dialog is read-only away from this Mac.
// A module may add its own tabs beside "Yapay zekâ" — window.osSuiteSettingsTabs = [{ id, label,
// render(el) }] — and open one with openAiSettings(id). Without any, the dialog has no tab bar.
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
                                    body: opts.body ? JSON.stringify(opts.body) : undefined });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  document.head.insertAdjacentHTML("beforeend", `<style>
.ai-dialog { border: 1px solid var(--border); border-radius: 14px; padding: 0; width: min(640px, calc(100vw - 24px));
  max-height: min(88vh, 900px); background: var(--surface); color: var(--text); box-shadow: 0 20px 50px rgba(0,0,0,.3); }
.ai-dialog[open] { display: flex; flex-direction: column; }
.ai-dialog::backdrop { background: rgba(10, 12, 16, .5); }
.ai-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border); }
.ai-head h3 { margin: 0; font-size: 16px; }
.ai-x { border: 0; background: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 4px 8px; border-radius: 6px; }
.ai-body { padding: 14px 18px 18px; overflow-y: auto; }
.ai-btn { border: 1px solid var(--border); background: var(--surface-2); color: var(--text); border-radius: 8px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.ai-btn:hover { border-color: color-mix(in srgb, var(--accent) 50%, var(--border)); }
.ai-btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.ai-btn.ghost { background: transparent; }
.ai-slot { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
.ai-slot.editing { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); }
.ai-slot + .ai-slot { margin-top: 12px; }
.ai-slot-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
.ai-slot-head span { font-weight: 600; color: var(--text); font-size: 13px; }
.ai-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ai-info { display: grid; gap: 2px; min-width: 0; flex: 1; }
.ai-info small { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.ai-logo { position: relative; flex: none; display: grid; place-items: center; border-radius: 9px; overflow: hidden;
  background: color-mix(in srgb, var(--c) 16%, var(--surface)); color: var(--c); font-weight: 700; font-size: 15px; }
.ai-logo img { position: absolute; inset: 0; margin: auto; width: 64%; height: 64%; object-fit: contain; }
.ai-logo.has-img { color: transparent; }
.ai-logo.empty { width: 34px; height: 34px; background: var(--surface-2); color: var(--muted); }
.ai-state { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 999px; }
.ai-state.ok { background: color-mix(in srgb, var(--up) 14%, transparent); color: var(--up); }
.ai-state.off { background: var(--surface-2); color: var(--muted); }
.ai-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; margin-top: 12px; }
.ai-pick { display: flex; align-items: center; gap: 8px; text-align: left; cursor: pointer; padding: 8px 10px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface-2); color: var(--text); font: inherit; font-size: 13px; font-weight: 600; flex-wrap: wrap; }
.ai-pick small { width: 100%; font-weight: 500; color: var(--muted); font-size: 11px; }
.ai-pick:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
.ai-pick.sel { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.ai-form { display: grid; gap: 10px; margin-top: 12px; }
.ai-form label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
.ai-form input { width: 100%; box-sizing: border-box; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
  padding: 9px 10px; font-size: 14px; color: var(--text); font-family: var(--mono, ui-monospace, monospace); }
.ai-form input:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.ai-adv summary { cursor: pointer; font-size: 12px; color: var(--muted); padding: 2px 0; }
.ai-adv[open] summary { margin-bottom: 8px; }
.ai-adv .hint { margin: 6px 0 0; }
.ai-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.ai-result { margin: 0; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.ai-result.ok { background: color-mix(in srgb, var(--up) 14%, transparent); color: var(--up); }
.ai-result.bad { background: color-mix(in srgb, var(--down) 14%, transparent); color: var(--down); }
.ai-swap { display: flex; justify-content: center; margin: 8px 0; }
.ai-foot { margin: 14px 0 0; font-size: 12px; color: var(--muted); }
.ai-dialog.tabbed { height: min(88vh, 720px); }    /* with tabs: one size, whichever tab is open */
.ai-dialog.tabbed .ai-body { flex: 1; min-height: 0; }
.ai-tabs { display: flex; gap: 2px; padding: 0 14px; border-bottom: 1px solid var(--border); overflow-x: auto; }
.ai-tabs[hidden] { display: none; }
.ai-tab { border: 0; background: none; color: var(--muted); font: inherit; font-size: 13px; padding: 10px 10px 8px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -1px; white-space: nowrap; }
.ai-tab:hover { color: var(--text); }
.ai-tab[aria-selected="true"] { color: var(--text); font-weight: 600; border-bottom-color: var(--accent); }
.ai-note { margin: 0 0 12px; padding: 8px 12px; border-radius: 8px; font-size: 13px; background: color-mix(in srgb, var(--up) 14%, transparent); color: var(--up); }
</style>`);
  document.body.insertAdjacentHTML("beforeend", `
<dialog class="ai-dialog" id="ai-dialog" aria-labelledby="ai-title">
  <div class="ai-head"><h3 id="ai-title">Ayarlar · Yapay zekâ</h3>
    <button class="ai-x" type="button" id="ai-close" title="Kapat (Esc)" aria-label="Kapat">✕</button></div>
  <div class="ai-tabs" id="ai-tabs" role="tablist" hidden></div>
  <div class="ai-body" id="ai-body"></div>
  <div class="ai-body" id="ai-tab-body" hidden></div>
</dialog>`);

  const SLOT_NAME = { primary: "Ana sağlayıcı", backup: "Yedek sağlayıcı" };
  // what the primary slot powers differs per module: set window.osSuiteAiPrimaryHint before opening
  const SLOT_HINT = { get primary() { return esc(window.osSuiteAiPrimaryHint || "Bu uygulamanın yapay zekâ işleri bunu kullanır"); },
                      backup: "Ana sağlayıcı hata verirse (kredi, kota, anahtar, ağ) iş otomatik buna geçer" };
  let st = null, editing = null, note = "";     // editing: {slot, provider, models, result}

  function logo(p, size = 34) {
    const letter = esc((p.name || "?").replace(/^(Google|Anthropic)\s+/, "")[0]);
    const id = esc(p.id || p.provider);
    return `<span class="ai-logo${logos.has(id) ? " has-img" : ""}" style="--c:${esc(p.color)};width:${size}px;height:${size}px">${
      logos.has(id) ? `<img src="/static/vendor/logos/${id}.svg" alt="">` : ""}${letter}</span>`;
  }

  // logos shipped in /static/vendor/logos (checked once; a missing one falls back to a letter badge)
  const logos = new Set();
  let logosChecked = null;
  function checkLogos(ids) {
    return logosChecked || (logosChecked = Promise.all(ids.map((id) => fetch(`/static/vendor/logos/${id}.svg`, { method: "HEAD" })
      .then((r) => { if (r.ok) logos.add(id); }).catch(() => {}))));
  }

  // the module's own tabs, if it registered any
  const extraTabs = () => (Array.isArray(window.osSuiteSettingsTabs) ? window.osSuiteSettingsTabs : []);
  function showTab(id) {
    const extra = extraTabs(), tab = extra.find((t) => t.id === id);
    const bar = $("#ai-tabs");
    bar.hidden = !extra.length;
    $("#ai-title").textContent = extra.length ? "Ayarlar" : "Ayarlar · Yapay zekâ";
    $("#ai-dialog").classList.toggle("tabbed", !!extra.length);
    bar.innerHTML = [{ id: "ai", label: "API" }, ...extra].map((t) =>
      `<button class="ai-tab" type="button" role="tab" data-tab="${esc(t.id)}" aria-selected="${(tab ? t.id === tab.id : t.id === "ai")}">${esc(t.label)}</button>`).join("");
    $("#ai-body").hidden = !!tab;
    $("#ai-tab-body").hidden = !tab;
    if (tab) tab.render($("#ai-tab-body"));
  }

  async function openSettings(tab = "ai") {
    editing = null;
    note = "";
    showTab(typeof tab === "string" ? tab : "ai");
    $("#ai-dialog").showModal();
    await load();
  }

  async function load() {
    try { st = await api("/api/settings/ai"); } catch (e) { $("#ai-body").textContent = e.message; return; }
    await checkLogos(st.providers.map((p) => p.id));
    render();
  }

  function slotCard(slot) {
    const s = st.slots[slot];
    const actions = st.editable
      ? `<button class="ai-btn" data-edit="${slot}">${s ? "Değiştir" : "Seç"}</button>${s ? `<button class="ai-btn ghost" data-remove="${slot}">Kaldır</button>` : ""}`
      : "";
    const body = s
      ? `${logo(s)}<div class="ai-info"><b>${esc(s.name)}</b>
           <small>${esc(s.model)} · ${s.masked ? `${esc(s.masked)} · ${esc(s.source)}` : esc(s.source || "anahtar yok")} · web araması ${s.search ? "var" : "yok"}</small></div>`
      : `<span class="ai-logo empty">+</span><div class="ai-info"><b>Tanımlı değil</b><small>${slot === "backup" ? "İsteğe bağlı" : "Bir sağlayıcı seç"}</small></div>`;
    return `<section class="ai-slot${editing?.slot === slot ? " editing" : ""}">
      <div class="ai-slot-head"><span>${SLOT_NAME[slot]}</span><small>${SLOT_HINT[slot]}</small></div>
      <div class="ai-row">${body}<span class="ai-state ${s ? (s.masked || s.source === "yerel" ? "ok" : "off") : "off"}" data-state="${slot}">${s ? (s.masked || s.source === "yerel" ? "Kayıtlı" : "Anahtar yok") : "Boş"}</span>${actions}</div>
      ${editing?.slot === slot ? editor() : ""}
    </section>`;
  }

  function editor() {
    const e = editing, p = st.providers.find((x) => x.id === e.provider);
    const grid = st.providers.map((x) => `
      <button type="button" class="ai-pick${x.id === e.provider ? " sel" : ""}" data-pick="${x.id}">${logo(x, 26)}<span>${esc(x.name)}</span>
        ${x.search ? "" : `<small>web araması yok</small>`}</button>`).join("");
    if (!p) return `<div class="ai-grid">${grid}</div><p class="hint">Önce sağlayıcıyı seç.</p>`;
    const cur = st.slots[e.slot]?.provider === p.id || Object.values(st.slots).some((s) => s?.provider === p.id && s.masked);
    const models = e.models?.length ? e.models : (p.model ? [p.model] : []);
    const r = e.result;
    const adv = e.adv ?? (!!e.model && e.model !== p.model);
    return `<div class="ai-grid">${grid}</div>
      <form class="ai-form" id="ai-form" autocomplete="off">
        <label>${esc(p.name)} API anahtarı
          <input id="ai-key" type="password" spellcheck="false" placeholder="${esc(p.hint)}${cur ? " · boş bırakırsan kayıtlı anahtar kalır" : ""}"></label>
        <details class="ai-adv" id="ai-adv"${adv ? " open" : ""}>
          <summary>Gelişmiş · model: ${esc(e.model || p.model)}${(e.model || p.model) === p.model ? " (önerilen)" : ""}</summary>
          <label>Model
            <input id="ai-model" list="ai-models" value="${esc(e.model || p.model || "")}" placeholder="${esc(p.model)}">
            <datalist id="ai-models">${models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist></label>
          <p class="hint">Çoğu kullanım için önerilen model yeterli. Test et, bu anahtarla kullanılabilen metin modellerini listeye getirir.</p>
        </details>
        <div class="ai-actions">
          <button class="ai-btn ghost" type="button" id="ai-cancel">Vazgeç</button>
          <button class="ai-btn" type="button" id="ai-test">Test et</button>
          <button class="ai-btn primary" type="submit">Kaydet</button>
        </div>
        ${r ? `<p class="ai-result ${r.ok ? "ok" : "bad"}">${r.ok ? "✓" : "⚠"} ${esc(r.message)}</p>` : ""}
      </form>`;
  }

  function render() {
    const both = st.slots.primary && st.slots.backup;
    $("#ai-body").innerHTML = `
      ${note ? `<p class="ai-note">✓ ${esc(note)}</p>` : ""}
      ${slotCard("primary")}
      ${st.editable && both ? `<div class="ai-swap"><button class="ai-btn ghost" id="ai-swap" type="button">⇅ Ana ve yedeği yer değiştir</button></div>` : ""}
      ${slotCard("backup")}
      ${st.editable ? "" : `<p class="ai-foot"><b>Bu cihazdan yalnızca görüntülenebilir; değiştirmek için uygulamanın çalıştığı bilgisayardan aç.</b></p>`}`;
  }

  function formValues() {
    if ($("#ai-adv")) editing.adv = $("#ai-adv").open;
    return { provider: editing.provider, key: $("#ai-key")?.value.trim() || null, model: $("#ai-model")?.value.trim() || null };
  }

  async function runTest() {
    const v = formValues();
    editing.model = v.model;
    editing.result = { ok: true, message: "Test ediliyor…" };
    render();
    try {
      const r = await api("/api/settings/ai/test", { method: "POST", body: v });
      editing.result = r;
      if (r.models?.length) editing.models = r.models;
    } catch (e) {
      editing.result = { ok: false, message: e.message };
    }
    render();
    if (v.key && $("#ai-key")) $("#ai-key").value = v.key;        // keep what was typed
  }

  async function save(force = false) {
    const v = formValues();
    editing.model = v.model;
    try {
      const r = await api(`/api/settings/ai/${editing.slot}`, { method: "PUT", body: { ...v, force } });
      st = r;
      editing = null;
      render();
      note = `Kaydedildi · ${r.test?.message || ""}`;
      render();
      window.dispatchEvent(new CustomEvent("ai-settings-changed"));
    } catch (e) {
      if (!force && window.confirm(`Test başarısız: ${e.message}\n\nYine de kaydedilsin mi?`)) return save(true);
      editing.result = { ok: false, message: e.message };
      render();
      if (v.key && $("#ai-key")) $("#ai-key").value = v.key;
    }
  }

  $("#ai-body").addEventListener("click", async (ev) => {
    const t = ev.target.closest("button");
    if (!t) return;
    if (t.dataset.edit) {
      const cur = st.slots[t.dataset.edit];
      editing = { slot: t.dataset.edit, provider: cur?.provider || null, model: cur?.model || null };
      render();
    } else if (t.dataset.pick) {
      const p = st.providers.find((x) => x.id === t.dataset.pick);
      editing = { slot: editing.slot, provider: p.id, model: st.slots[editing.slot]?.provider === p.id ? st.slots[editing.slot].model : p.model };
      render();
      $("#ai-key")?.focus();
    } else if (t.dataset.remove) {
      const s = st.slots[t.dataset.remove];
      if (!window.confirm(`${SLOT_NAME[t.dataset.remove]} kaldırılsın mı?\n\n${s.name} bu yuvadan çıkarılacak; başka yuvada kullanılmıyorsa anahtarı da Anahtar Zinciri'nden silinir.`)) return;
      try { st = await api(`/api/settings/ai/${t.dataset.remove}`, { method: "DELETE" }); note = ""; render(); window.dispatchEvent(new CustomEvent("ai-settings-changed")); } catch (e) { window.alert(e.message); }
    } else if (t.id === "ai-swap") {
      try { st = await api("/api/settings/ai/swap", { method: "POST" }); note = ""; render(); window.dispatchEvent(new CustomEvent("ai-settings-changed")); } catch (e) { window.alert(e.message); }
    } else if (t.id === "ai-cancel") {
      editing = null;
      render();
    } else if (t.id === "ai-test") {
      runTest();
    }
  });
  $("#ai-body").addEventListener("submit", (ev) => { ev.preventDefault(); save(); });

  document.addEventListener("click", (ev) => {
    const opener = ev.target.closest("[data-open-settings]");
    if (opener) openSettings(opener.dataset.openSettings || "ai");
  });
  $("#ai-tabs").addEventListener("click", (ev) => { const t = ev.target.closest("[data-tab]"); if (t) showTab(t.dataset.tab); });
  $("#ai-close").addEventListener("click", () => $("#ai-dialog").close());
  $("#ai-dialog").addEventListener("click", (e) => { if (e.target.id === "ai-dialog") e.target.close(); });   // backdrop
  window.openAiSettings = openSettings;

})();
