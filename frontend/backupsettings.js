// ------------------------------------------------------------ Ayarlar → Yedek (shared)
// ONE FILE, COPIED AS-IS into FinanceOS and CommerceOS (next to aisettings.js, loaded after it and after
// any script that sets window.osSuiteSettingsTabs). Adds a "Yedek" tab: where the daily backup goes
// (data/backups, and encrypted to iCloud Drive / OneDrive or a chosen folder), the backup passphrase
// (write-only, kept in the system's secret store) and "Şimdi yedekle". Uses aisettings.js's styles.
(() => {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
                                    body: opts.body ? JSON.stringify(opts.body) : undefined });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }
  const day = (d) => (d ? d.split("-").reverse().join(".") : "henüz yok");

  document.head.insertAdjacentHTML("beforeend", `<style>
.bk-rows { display: grid; gap: 10px; margin: 4px 0 14px; }
.bk-row { display: flex; justify-content: space-between; align-items: baseline; gap: 6px 14px; flex-wrap: wrap; font-size: 13px; }
.bk-row > span:first-child { color: var(--muted); }
.bk-row > span:last-child { text-align: right; overflow-wrap: anywhere; }
.bk-box { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-top: 12px; }
.bk-box h4 { margin: 0 0 4px; font-size: 13px; }
.bk-box p { margin: 0 0 10px; font-size: 12px; color: var(--muted); }
</style>`);

  let editing = null;      // "pass" | "dir" | null
  let result = null;       // { ok, message }

  async function render(el) {
    let b;
    try { b = await api("/api/settings/backup"); } catch (e) { el.textContent = e.message; return; }
    const cloud = b.cloud_dir
      ? `${esc(b.cloud_dir)}${b.cloud_name ? ` <small>(${esc(b.cloud_name)})</small>` : ""}`
      : "Bulut klasörü bulunamadı";
    const pass = b.passphrase_set ? `<span class="ai-state ok">Kayıtlı</span>` : `<span class="ai-state off">Tanımlı değil</span>`;
    const rows = `<div class="bk-rows">
      <div class="bk-row"><span>Günlük yedek</span><span>${esc(b.local_dir)} · son ${esc(b.keep)} gün · son: ${day(b.last_local)}</span></div>
      <div class="bk-row"><span>Şifreli bulut kopyası</span><span>${!b.cloud_on ? "kapalı"
        : !b.passphrase_set ? `<span class="ai-state off">İsteğe bağlı · kapalı</span>`
        : `${cloud}${b.cloud_dir ? ` · son: ${day(b.last_cloud)}` : ""}`}</span></div>
      <div class="bk-row"><span>Yedek şifresi</span><span>${pass}</span></div>
      <div class="bk-row"><span>Şifre nerede</span><span>${esc(b.store)}</span></div>
    </div>`;
    // the cloud copy is optional: until a passphrase turns it on, a plain note instead of a warning
    const note = b.cloud_on && !b.passphrase_set
      ? `<p class="hint">Yedekler bu bilgisayarda tutulur. İstersen bir şifre belirle; şifreli bir kopya bulut klasörüne${b.cloud_name ? ` (${esc(b.cloud_name)})` : ""} de gider.</p>` : "";
    const msg = result ? `<p class="ai-result ${result.ok ? "ok" : "bad"}">${result.ok ? "✓" : "⚠"} ${esc(result.message)}</p>` : "";
    if (!b.editable) {
      el.innerHTML = rows + `<p class="hint">Değiştirmek için bu ayarı uygulamanın çalıştığı bilgisayardan aç.</p>`;
      return;
    }
    let form = "";
    if (editing === "pass") {
      form = `<form class="bk-box ai-form" id="bk-pass-form" autocomplete="off">
        <h4>${b.passphrase_set ? "Yedek şifresini değiştir" : "Yedek şifresi belirle"}</h4>
        <p>Buluttaki kopyalar bu şifreyle açılır. Unutursan o kopyalar açılamaz; bir yere not et. Bu bilgisayardaki yedekler şifresizdir.</p>
        <label>Şifre (en az 8 karakter)<input id="bk-pass" type="password" autocomplete="new-password" spellcheck="false"></label>
        <label>Şifre tekrar<input id="bk-pass2" type="password" autocomplete="new-password" spellcheck="false"></label>
        <div class="ai-actions"><button class="ai-btn ghost" type="button" data-bk="cancel">Vazgeç</button>
          <button class="ai-btn primary" type="submit">Kaydet</button></div></form>`;
    } else if (editing === "dir") {
      form = `<form class="bk-box ai-form" id="bk-dir-form" autocomplete="off">
        <h4>Bulut kopyasının klasörü</h4>
        <p>Tam klasör yolu gir; Dropbox ya da Google Drive klasörü de olabilir. Varsayılan, iCloud Drive ya da OneDrive içindeki yedek klasörüdür.</p>
        <label>Klasör<input id="bk-dir" spellcheck="false" value="${esc(b.custom_dir ? b.cloud_dir : "")}" placeholder="${esc(b.cloud_dir || "")}"></label>
        <div class="ai-actions"><button class="ai-btn ghost" type="button" data-bk="cancel">Vazgeç</button>
          ${b.custom_dir ? `<button class="ai-btn" type="button" data-bk="default-dir">Varsayılana dön</button>` : ""}
          <button class="ai-btn primary" type="submit">Kaydet</button></div></form>`;
    }
    el.innerHTML = rows + note + `<div class="ai-actions">
        <button class="ai-btn" type="button" data-bk="dir">Klasörü değiştir</button>
        <button class="ai-btn" type="button" data-bk="pass">${b.passphrase_set ? "Şifreyi değiştir" : "Bulut kopyasını aç"}</button>
        <button class="ai-btn primary" type="button" data-bk="run">Şimdi yedekle</button></div>` + form + msg;
    el.querySelector("#bk-pass, #bk-dir")?.focus();

    el.onclick = async (ev) => {
      const t = ev.target.closest("[data-bk]");
      if (!t) return;
      const act = t.dataset.bk;
      if (act === "cancel") { editing = null; result = null; return render(el); }
      if (act === "pass" || act === "dir") { editing = act; result = null; return render(el); }
      try {
        if (act === "run") {
          result = { ok: true, message: "Yedekleniyor…" };
          await render(el);
          result = { ok: true, message: (await api("/api/settings/backup/run", { method: "POST" })).message };
        } else if (act === "default-dir") {
          await api("/api/settings/backup", { method: "PUT", body: { default_dir: true } });
          editing = null;
          result = { ok: true, message: "Algılanan bulut klasörü kullanılacak" };
        }
      } catch (e) { result = { ok: false, message: e.message }; }
      render(el);
    };
    el.onsubmit = async (ev) => {
      ev.preventDefault();
      try {
        if (ev.target.id === "bk-pass-form") {
          const a = el.querySelector("#bk-pass").value, c = el.querySelector("#bk-pass2").value;
          if (a !== c) { result = { ok: false, message: "İki şifre aynı değil" }; return render(el); }
          await api("/api/settings/backup", { method: "PUT", body: { passphrase: a } });
          result = { ok: true, message: "Yedek şifresi kaydedildi" };
        } else {
          await api("/api/settings/backup", { method: "PUT", body: { dir: el.querySelector("#bk-dir").value } });
          result = { ok: true, message: "Klasör kaydedildi" };
        }
        editing = null;
      } catch (e) { result = { ok: false, message: e.message }; }
      render(el);
    };
  }

  window.osSuiteSettingsTabs = [...(Array.isArray(window.osSuiteSettingsTabs) ? window.osSuiteSettingsTabs : []),
    { id: "backup", label: "Yedek", render: (el) => { editing = null; result = null; return render(el); } }];
})();
