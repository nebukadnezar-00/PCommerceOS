// CommerceOS: my stores (logo tiles), product search (Akakçe quick / Gemini deep) and history.
(() => {
  const $ = (s) => document.querySelector(s);
  const state = { sites: [], groups: [], groupFilter: "all", scope: "all", query: "", result: null, editing: false,
    busy: false, tracked: [], filters: new Set(), cart: { items: [], result: null } };

  // ------------------------------------------------------------ helpers
  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
    return el;
  }

  // one icon set (stroke icons, 24-unit grid) instead of emoji and text symbols; constants only
  const ICONS = {
    x: `<path d="M18 6 6 18M6 6l12 12"/>`,
    mail: `<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3.5 6.5 8.5 6.5 8.5-6.5"/>`,
    trash: `<path d="M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>`,
    check: `<path d="M20 6 9 17l-5-5"/>`,
    refresh: `<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>`,
    cart: `<circle cx="9" cy="20" r="1.3"/><circle cx="18" cy="20" r="1.3"/><path d="M2.5 3.5h2.6l2.5 11.6a1.2 1.2 0 0 0 1.2.9h9.3a1.2 1.2 0 0 0 1.2-.9L21 7.5H6"/>`,
    bell: `<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>`,
    package: `<path d="M12 3 3.5 7.5v9L12 21l8.5-4.5v-9z"/><path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"/>`,
    dots: `<circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/>`,
    chevron: `<path d="m6 9 6 6 6-6"/>`,
    plus: `<path d="M12 5v14M5 12h14"/>`,
    search: `<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>`,
    grid: `<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>`,
    pencil: `<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>`,
  };
  function icon(name, size = 18) {
    const t = document.createElement("template");
    t.innerHTML = `<svg class="ic" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" ` +
      `stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`;
    return t.content.firstChild;
  }

  // replaceChildren() would print null/false as text: skip them, like h() does
  function fill(el, ...kids) {
    el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
  }

  async function api(path, opts = {}) {
    const init = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
    if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
    const r = await fetch(path, { keepalive: init.method === "DELETE" || init.method === "PATCH", ...init });
    let data = null;
    try { data = await r.json(); } catch (_) { /* empty body */ }
    if (!r.ok) {
      const err = new Error((data && data.detail) || `Hata (HTTP ${r.status})`);
      err.status = r.status;
      throw err;
    }
    return data;
  }

  const money = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtPrice = (p, cur = "TL") => `${money.format(p)} ${cur}`;
  const fmtTokens = (n) => (n >= 1000 ? `${(n / 1000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })}k` : String(n));

  function ago(iso) {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "az önce";
    if (s < 3600) return `${Math.floor(s / 60)} dk önce`;
    if (s < 86400) return `${Math.floor(s / 3600)} sa önce`;
    if (s < 7 * 86400) return `${Math.floor(s / 86400)} gün önce`;
    return new Date(iso).toLocaleDateString("tr-TR");
  }

  let toastTimer;
  function toast(msg, action = null, ms = 3500) {
    const t = $("#toast");
    fill(t, h("span", {}, msg), action ? h("button", { class: "toast-act", type: "button",
      onclick: () => { t.hidden = true; clearTimeout(toastTimer); action.run(); } }, action.label) : null);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (t.hidden = true), ms);
  }

  // Deletions happen on screen at once and are saved a few seconds later — no confirmation dialogs.
  // "Geri al" sits where the removed thing was (`el`), with a countdown; without an element it is
  // in the toast. Leaving the page saves whatever is still waiting.
  const UNDO_MS = 5000;
  const CART_UNDO_MS = UNDO_MS / 2;   // the cart is quick to fill again: a shorter wait
  const pendingUndo = new Set();
  function undoable(message, { el = null, hide = () => {}, restore = () => {}, commit, ms = UNDO_MS, ic = "trash" }) {
    const hadFocus = el && el.contains(document.activeElement);
    let strip = null;
    // after a commit the list has been redrawn: the old element is gone, a lasting container shows again
    const show = () => { if (strip) strip.remove(); if (el) el.hidden = false; };
    if (el) el.hidden = true;
    hide();
    const job = { done: false };
    job.finish = async () => {
      if (job.done) return;
      job.done = true;
      clearTimeout(job.timer);
      pendingUndo.delete(job);
      try { await commit(); show(); } catch (e) { show(); restore(); toast(e.message); }
    };
    const undo = () => {
      if (job.done) return;
      job.done = true;
      clearTimeout(job.timer);
      pendingUndo.delete(job);
      show();
      restore();
    };
    job.timer = setTimeout(job.finish, ms);
    pendingUndo.add(job);
    if (!el || !el.parentNode) { toast(message, { label: "Geri al", run: undo }, ms); return; }
    const btn = h("button", { class: "undo-act", type: "button", onclick: undo }, "Geri al");
    strip = h("div", { class: "undo-strip", role: "status" },
      h("span", { class: "undo-msg" }, icon(ic, 15), h("span", {}, message)), btn,
      h("span", { class: "undo-bar", style: `animation-duration:${ms}ms`, "aria-hidden": "true" }));
    el.before(strip);
    if (hadFocus) btn.focus();
  }
  addEventListener("pagehide", () => pendingUndo.forEach((job) => job.finish()));


  function logo(site, label) {
    const name = (site && site.name) || label || "?";
    if (site && site.logo) return h("span", { class: "logo" }, h("img", { src: site.logo, alt: "", loading: "lazy" }));
    return h("span", { class: "logo initial", "aria-hidden": "true" }, name.trim().charAt(0).toLocaleUpperCase("tr-TR"));
  }

  const siteById = (id) => state.sites.find((s) => s.id === id);
  const siteSearch = (s, q) => s.search_url.replace("{q}", encodeURIComponent(q).replace(/%20/g, "+"));

  // ------------------------------------------------------------ status
  // heartbeat: green = healthy, amber = works with a warning, blue = searching, red = server down
  // the header says what a problem means for the user, not which part failed (details are in the popover)
  function plainIssue(i) {
    if (/fiyat kaynağı/i.test(i)) return "Bazı mağazalara şu an ulaşılamıyor";
    if (/yapısı değişmiş|okunamıyor/i.test(i)) return "Fiyatlar şu an okunamıyor";
    if (/Gemini|derin arama/i.test(i)) return "Derin arama kapalı";
    if (/yedek/i.test(i)) return "Yedekleme yapılamadı";
    return "Bir sorun var";
  }

  function renderHealth() {
    const box = $("#status"), text = $("#status-text"), s = state.status;
    if (!s) {
      box.className = "status down";
      text.textContent = "Uygulama yanıt vermiyor";
      renderHealthPop(null);
      return;
    }
    const issues = [...s.health.issues, ...(s.backup_warning ? [s.backup_warning] : [])];
    // all well: "Sağlıklı" with its heartbeat; otherwise the first problem in plain words
    box.className = issues.length ? "status warn" : "status";
    text.textContent = issues.length ? plainIssue(issues[0]) + (issues.length > 1 ? ` (+${issues.length - 1})` : "") : "Sağlıklı";
    box.setAttribute("aria-label", issues.length ? text.textContent : "Durum: sağlıklı");
    if (state.busy || s.tracking.running) {
      box.className = "status running";
      text.textContent = state.busy === "deep" ? "Derin arama…" : state.busy === "cart" ? "Sepet karşılaştırılıyor…"
        : state.busy ? "Aranıyor…" : "Fiyatlar kontrol ediliyor…";
    }
    renderHealthPop(s, issues);
  }

  // what used to be the native tooltip, plus this month's Gemini tokens (no longer in the header)
  function renderHealthPop(s, issues = []) {
    const pop = $("#status-pop");
    if (!s) {
      fill(pop, h("div", { class: "issue" }, "CommerceOS sunucusuna ulaşılamıyor; uygulama kapalı olabilir."));
      return;
    }
    const hl = s.health, row = (k, v) => h("div", { class: "row" }, h("span", {}, k), h("b", {}, v));
    fill(pop, 
      ...issues.map((i) => h("div", { class: "issue" }, i)),
      row("Hızlı arama", hl.akakce === null ? "kontrol ediliyor" : hl.akakce ? "hazır" : "diğer kaynaklarla"),
      row("Fiyat okuma", hl.akakce_parse === null ? "kontrol ediliyor" : hl.akakce_parse ? "çalışıyor" : "bozuk"),
      row("Derin arama", hl.ai_ready ? "hazır" : "sağlayıcı yok (⚙ Ayarlar)"),
      row("Sitelerim", `${hl.sites} site${hl.missing_logos.length ? ` · logosuz: ${hl.missing_logos.join(", ")}` : ""}`),
      row("Fiyat takibi", `${s.tracking.items} ürün${s.tracking.last_run ? ` · ${ago(s.tracking.last_run)}` : ""}`),
      h("div", { class: "row tokens" }, h("span", {}, "Yapay zekâ (bu ay)"),
        h("button", { class: "link-btn", type: "button", "data-open-settings": "usage", title: "Kullanım ve maliyet" },
          `${s.month.tokens.toLocaleString("tr-TR")} token · ${s.month.searches} derin arama${s.month.cost ? ` · ${usd(s.month.cost)}` : ""}`)),
      ...(s.ai || []).map((a, i) => h("div", { class: "row" }, h("span", {}, i ? "Yedek" : "Ana"), h("b", {}, `${a.provider} · ${a.model}`))));
  }

  // touch screens have no hover: a tap opens and closes the box
  $("#status").addEventListener("click", (e) => {
    const wrap = $("#status-wrap"), open = !wrap.classList.contains("open");
    wrap.classList.toggle("open", open);
    e.currentTarget.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#status-wrap")) { $("#status-wrap").classList.remove("open"); $("#status").setAttribute("aria-expanded", "false"); }
  });

  let statusTimer;
  async function loadStatus() {
    clearTimeout(statusTimer);
    try {
      const s = await api("/api/status");
      state.status = s;
      if (state.onStatus) { state.onStatus(s); state.onStatus = null; }
      if (state.onAkakce && s.health.akakce !== null) { state.onAkakce(s.health.akakce); state.onAkakce = null; }
      renderAlertsBadge(s.alerts_unseen);
      renderTrackingMeta(s.tracking);
      // a running price check finishes in the background: reload the list when it ends
      const wasRunning = state.trackRunning;
      state.trackRunning = s.tracking.running;
      if (wasRunning && !s.tracking.running) loadTracked();
      // the same for an order-email scan; a newly set-up mailbox shows its first scan
      const wasScanning = state.ordersRunning, wasConfigured = state.orders.state && state.orders.state.configured;
      state.ordersRunning = s.orders.running;
      renderOrdersMeta(s.orders);
      if ((wasScanning && !s.orders.running) || (state.orders.state && wasConfigured !== s.orders.configured)) loadOrders();
      if (s.orders.configured && !s.orders.last_scan && !s.orders.running && !s.orders.error && !state.firstScanAsked) {
        state.firstScanAsked = true;
        api("/api/orders/scan", { method: "POST" }).then(() => { state.ordersRunning = true; }, () => {});
      }
      // the first Akakçe check runs in the background: look again soon to show its result
      statusTimer = setTimeout(loadStatus, s.health.akakce === null || s.tracking.running || s.orders.running ? 3000 : 30000);
    } catch (e) {
      state.status = null;
      if (state.onStatus) { state.onStatusFail(e); state.onStatus = null; }
      statusTimer = setTimeout(loadStatus, 10000);
    }
    renderHealth();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadStatus(); });
  window.addEventListener("ai-settings-changed", () => loadStatus());      // ⚙ Ayarlar saved a provider

  // ------------------------------------------------------------ ⚙ Ayarlar → Kullanım ve maliyet
  // a tab beside "API" in the shared settings dialog: what the AI cost, in total, over time and per part
  const PERIOD_LABEL = { today: "Bugün", week: "Haftalık", month: "1 ay", quarter: "3 ay" };
  const usd = (v) => `$${v.toLocaleString("tr-TR", { minimumFractionDigits: v && v < 0.01 ? 4 : 2, maximumFractionDigits: v && v < 0.01 ? 4 : 2 })}`;
  let usagePeriod = "month";

  async function renderUsage(el) {
    let u;
    try { u = await api(`/api/usage?period=${usagePeriod}`); } catch (e) { fill(el, h("p", { class: "muted" }, e.message)); return; }
    const maxTok = Math.max(1, ...u.sections.map((x) => x.tokens));
    const costText = (c, unpriced) => (unpriced && !c ? "fiyat ?" : usd(c) + (unpriced ? " +?" : ""));
    fill(el,
      h("div", { class: "seg us-periods", role: "group", "aria-label": "Dönem" }, Object.entries(PERIOD_LABEL).map(([k, label]) =>
        h("button", { type: "button", "aria-pressed": String(k === usagePeriod), onclick: () => { usagePeriod = k; renderUsage(el); } }, label))),
      h("div", { class: "us-kpis" },
        h("div", {}, h("small", {}, "Toplam maliyet"), h("b", {}, costText(u.cost, u.unpriced)), h("small", {}, "tahmini, liste fiyatıyla")),
        h("div", {}, h("small", {}, "Token"), h("b", {}, fmtTokens(u.tokens)),
          h("small", {}, `giriş ${fmtTokens(u.prompt_tokens)} · çıkış ${fmtTokens(u.output_tokens)}`)),
        h("div", {}, h("small", {}, "İstek"), h("b", {}, String(u.requests)), h("small", {}, u.backup ? `yedek: ${u.backup} kez` : "yedek kullanılmadı"))),
      usageChart(u),
      h("div", { class: "us-list" },
        h("div", { class: "us-row us-headrow" }, h("span", {}, "Bölüm"), h("span"), h("span", {}, "Token"), h("span", {}, "Maliyet")),
        u.sections.map((x) => h("div", { class: "us-row" + (x.spends ? "" : " none") },
          h("span", { class: "us-name" }, x.name, x.spends && x.requests ? h("small", {}, ` · ${x.requests} arama`) : null),
          x.spends ? h("span", { class: "us-bar" }, h("i", { style: `width:${Math.round((x.tokens / maxTok) * 100)}%` })) : h("span", { class: "muted small" }, "token yok"),
          h("span", { class: "num" }, x.spends ? fmtTokens(x.tokens) : "—"),
          h("span", { class: "num" }, x.spends ? costText(x.cost, x.unpriced) : "—")))));
  }

  // cost per hour (today), day (7 / 30 days) or week (90 days); each bar says its numbers on hover/focus
  function usageChart(u) {
    const unit = { today: "Saatlik", week: "Günlük", month: "Günlük", quarter: "Haftalık" }[u.period];
    const head = h("div", { class: "us-chart-head" }, h("span", {}, `${unit} maliyet`));
    if (!u.requests) return h("div", { class: "us-chart" }, head, h("p", { class: "us-chart-empty" }, "Bu dönemde token harcanmadı."));
    const max = Math.max(...u.series.map((b) => b.cost), 1e-9);
    const tipEl = h("span", { class: "us-tip" }, "Ayrıntı için bir çubuğa dokun");
    const when = (b) => (u.period === "today" ? `bugün ${b.label}` : u.period === "quarter" ? `${b.label} haftası` : b.label);
    const bars = u.series.map((b) => {
      const text = `${when(b)} · ${usd(b.cost)} · ${fmtTokens(b.tokens)} token · ${b.requests} arama`;
      const show = () => { tipEl.textContent = text; };
      return h("span", { class: "us-col", tabindex: b.requests ? "0" : null, "aria-label": b.requests ? text : null,
        onmouseenter: show, onfocus: show, onclick: show },
        h("i", { class: b.requests ? "" : "z", style: b.requests ? `height:${Math.max(6, Math.round((b.cost / max) * 100))}%` : "" }));
    });
    const mid = u.series[Math.floor(u.series.length / 2)];
    return h("div", { class: "us-chart" }, head,
      h("div", { class: "us-bars", role: "img", "aria-label": `${unit} maliyet grafiği` }, bars),
      h("div", { class: "us-axis" }, h("span", {}, u.series[0].label), h("span", {}, mid.label),
        h("span", {}, u.period === "today" ? "23:00" : "Bugün")),
      tipEl);
  }

  // ------------------------------------------------------------ ⚙ Ayarlar → E-posta (Gmail for Siparişlerim)
  let mailEditing = false;

  async function renderMail(el) {
    let m;
    try { m = await api("/api/settings/mail"); } catch (e) { fill(el, h("p", { class: "muted" }, e.message)); return; }
    const head = h("div", { class: "mail-head" },
      h("span", { class: "mail-logo", "aria-hidden": "true" }, icon("mail", 20)),
      h("div", { class: "mail-who" }, h("b", {}, "Gmail"),
        m.configured ? h("small", {}, [m.user, m.last_scan ? `son tarama ${ago(m.last_scan)}` : null].filter(Boolean).join(" · ")) : null),
      h("span", { class: "mail-state" + (m.configured ? " ok" : "") }, m.configured ? "Bağlı" : "Bağlı değil"));
    const about = h("p", { class: "muted small" }, "Siparişlerin, sitelerinden gelen e-postalardan okunur. E-postalar yalnızca okunur, ",
      "hiçbiri değiştirilmez ve token harcanmaz. Gelen kutusu, Spam ve Çöp kutusu taranır.");
    if (m.configured && !mailEditing) {
      fill(el, head, about, m.editable ? h("div", { class: "mail-actions" },
        h("button", { class: "btn sm", type: "button", onclick: () => { mailEditing = true; renderMail(el); } }, "Şifreyi değiştir"),
        h("button", { class: "btn sm danger-text", type: "button", onclick: async () => {
          if (!window.confirm("Gmail bağlantısı kaldırılsın mı?\n\nUygulama şifresi bu bilgisayardan silinir. Okunmuş siparişlerin kalır.")) return;
          try { await api("/api/settings/mail", { method: "DELETE" }); loadStatus(); loadOrders(); renderMail(el); } catch (e) { toast(e.message); }
        } }, "Bağlantıyı kaldır")) : h("p", { class: "muted small" }, "Değiştirmek için bu ayarı uygulamanın çalıştığı bilgisayardan aç."));
      return;
    }
    if (!m.editable) { fill(el, head, about, h("p", { class: "muted small" }, "Gmail'i bağlamak için bu ayarı uygulamanın çalıştığı bilgisayardan aç.")); return; }
    const user = h("input", { type: "email", autocomplete: "username", placeholder: "adin@gmail.com", spellcheck: "false" });
    const pass = h("input", { type: "password", autocomplete: "new-password", placeholder: "abcd efgh ijkl mnop", spellcheck: "false" });
    const result = h("p", { class: "mail-result", hidden: true });
    const say = (ok, text) => { result.hidden = false; result.className = "mail-result " + (ok ? "ok" : "bad"); result.textContent = (ok ? "✓ " : "⚠ ") + text; };
    const body = () => ({ user: user.value.trim(), password: pass.value });
    const form = h("form", { class: "mail-form", onsubmit: async (e) => {
      e.preventDefault();
      say(true, "Gmail'e bağlanılıyor…");
      try {
        const r = await api("/api/settings/mail", { method: "PUT", body: body() });
        mailEditing = false;
        toast(`Gmail bağlandı · ${r.message}`);
        loadStatus();
        renderMail(el);
      } catch (err) { say(false, err.message); }
    } },
      h("label", {}, "Gmail adresi", user),
      h("label", {}, "Uygulama şifresi",
        h("small", { class: "mail-note" }, "Gmail şifren değil: Google'ın bu uygulama için verdiği 16 harflik ayrı şifre. ",
          "Yalnızca e-posta okur, istediğin an Google hesabından silebilirsin."), pass),
      h("p", { class: "muted small" },
        h("a", { href: "https://myaccount.google.com/apppasswords", target: "_blank", rel: "noopener noreferrer" }, "Uygulama şifresi nasıl alınır ↗"),
        " · Google hesabında 2 adımlı doğrulama açık olmalı."),
      h("div", { class: "mail-actions" },
        m.configured ? h("button", { class: "btn sm ghost", type: "button", onclick: () => { mailEditing = false; renderMail(el); } }, "Vazgeç") : null,
        h("button", { class: "btn sm", type: "button", onclick: async () => {
          say(true, "Deneniyor…");
          try { const r = await api("/api/settings/mail/test", { method: "POST", body: body() }); say(r.ok, r.message); }
          catch (err) { say(false, err.message); }
        } }, "Test et"),
        h("button", { class: "btn sm primary", type: "submit" }, "Kaydet")),
      result);
    fill(el, head, about, form);
    user.focus();
  }

  window.osSuiteSettingsTabs = [
    { id: "mail", label: "E-posta", render: renderMail },
    { id: "usage", label: "Kullanım ve maliyet", render: renderUsage },
  ];

  // ------------------------------------------------------------ my stores
  async function loadSites() {
    const [list, groups] = await Promise.all([api("/api/sites"), api("/api/groups")]);
    state.sites = list;
    state.groups = groups;
    if (state.groupFilter !== "all" && !groups.some((g) => String(g.id) === state.groupFilter)) state.groupFilter = "all";
    renderSites();
    renderDock();
    setScope(state.scope);
    if (state.result) renderResult(state.result);
    if (state.orders.items.length) renderOrders();   // their store logos
  }

  const groupKey = (gid) => (gid == null ? "" : String(gid));

  function siteTile(s) {
    const tile = h("a", { class: "site", href: s.url, target: "_blank", rel: "noopener", title: s.url,
      draggable: "false", "data-id": s.id,
      onclick: (e) => { if (state.editing || drag.suppressClick) e.preventDefault(); drag.suppressClick = false; },
      onkeydown: (e) => keyMove(e, tile) },
      logo(s), h("span", { class: "name" }, s.name), h("span", { class: "domain" }, s.domain),
      h("span", { class: "tools" },
        h("button", { class: "icon-btn", type: "button", title: "Adını değiştir", "aria-label": `${s.name} adını değiştir`,
          onclick: (e) => { e.preventDefault(); renameSite(s); } }, icon("pencil", 15)),
        h("button", { class: "icon-btn", type: "button", title: "Logoyu yenile", "aria-label": `${s.name} logosunu yenile`,
          onclick: (e) => { e.preventDefault(); refreshLogo(s, tile); } }, icon("refresh", 15))),
      // shown while editing: a clear, labelled remove button under the store's name
      h("button", { class: "site-del", type: "button", "aria-label": `${s.name} sitesini sil`,
        onclick: (e) => { e.preventDefault(); removeSite(s, tile); } }, "Sil"));
    return tile;
  }

  // Stores in titled, collapsible groups ("Diğer" = no group, always last) with filter chips on top.
  // Without any group the card is one plain grid, as before.
  function renderSites() {
    const box = $("#sites");
    box.classList.toggle("editing", state.editing);
    $("#sites-count").textContent = state.sites.length
      ? `${state.sites.length} site${state.groups.length ? ` · ${state.groups.length} grup` : ""}` : "";
    // adding a site is in the header ("Site ekle"), not a tile at the end of the list
    const grid = (gid, list) => h("div", { class: "sites-grid", "data-group": groupKey(gid) }, list.map(siteTile));

    if (!state.groups.length) {
      fill(box, grid(null, state.sites));
    } else {
      const byGroup = (gid) => state.sites.filter((s) => (s.group_id ?? null) === gid);
      const sections = [...state.groups.map((g) => ({ g, gid: g.id, name: g.name, list: byGroup(g.id) })),
        { g: null, gid: null, name: "Diğer", list: byGroup(null) }];
      const shown = state.groupFilter === "all" ? sections : sections.filter((s) => groupKey(s.gid) === state.groupFilter);
      const chips = h("div", { class: "group-chips", role: "group", "aria-label": "Grup filtresi" },
        [{ key: "all", name: "Tümü", n: state.sites.length },
          ...sections.filter((s) => s.g || s.list.length).map((s) => ({ key: groupKey(s.gid), name: s.name, n: s.list.length }))]
          .map((c) => h("button", { class: "chip", type: "button", "aria-pressed": String(state.groupFilter === c.key),
            onclick: () => setGroupFilter(c.key) }, `${c.name} · ${c.n}`)));
      const last = shown[shown.length - 1];
      fill(box, chips, ...shown
        .filter((s) => s.g || s.list.length || s === last)
        .map((s) => {
          const collapsed = !!(s.g && s.g.collapsed) && state.groupFilter === "all";
          return h("section", { class: "site-group" + (collapsed ? " collapsed" : ""), "data-group": groupKey(s.gid) },
            h("div", { class: "group-head" },
              h("button", { class: "group-toggle", type: "button", "aria-expanded": String(!collapsed),
                onclick: () => s.g && toggleGroup(s.g) }, h("span", { class: "chev", "aria-hidden": "true" }, icon("chevron", 15)),
                h("b", {}, s.name), h("span", { class: "muted small" }, `${s.list.length}`)),
              s.g && state.editing ? h("span", { class: "group-tools" },
                h("button", { class: "icon-btn", type: "button", title: "Grubun adını değiştir", "aria-label": `${s.name} grubunun adını değiştir`, onclick: () => renameGroup(s.g) }, icon("pencil", 15)),
                h("button", { class: "icon-btn del", type: "button", title: "Grubu sil (siteler Diğer'e geçer)", "aria-label": `${s.name} grubunu sil`, onclick: () => removeGroup(s.g) }, icon("x", 15)))
                : null),
            collapsed ? null : grid(s.gid, s.list));
        }));
    }
    box.querySelectorAll("img").forEach((img) => img.setAttribute("draggable", "false"));
  }

  function setGroupFilter(key) {
    state.groupFilter = key;
    try { localStorage.setItem("commerce_group_filter", key); } catch (_) { /* private mode */ }
    renderSites();
    renderDock();
  }

  async function toggleGroup(g) {
    g.collapsed = g.collapsed ? 0 : 1;
    renderSites();
    try { await api(`/api/groups/${g.id}`, { method: "PATCH", body: { collapsed: !!g.collapsed } }); }
    catch (e) { toast(e.message); loadSites(); }
  }

  async function addGroup() {
    const name = prompt("Yeni grubun adı (ör. Elektronik, Market, Seyahat)");
    if (!name || !name.trim()) return;
    try { await api("/api/groups", { method: "POST", body: { name } }); await loadSites(); toast(`"${name.trim()}" grubu eklendi — siteleri sürükleyerek taşıyabilirsin`); }
    catch (e) { toast(e.message); }
  }

  async function renameGroup(g) {
    const name = prompt("Grup adı", g.name);
    if (!name || name.trim() === g.name) return;
    try { await api(`/api/groups/${g.id}`, { method: "PATCH", body: { name } }); await loadSites(); }
    catch (e) { toast(e.message); }
  }

  function removeGroup(g) {
    const box = document.querySelector(`#sites .site-group[data-group="${g.id}"]`);
    undoable(`"${g.name}" grubu silindi — siteleri "Diğer"e geçti`, {
      el: box,
      commit: async () => {
        await api(`/api/groups/${g.id}`, { method: "DELETE" });
        if (state.scope === `mine:${g.id}`) setScope("mine");
        await loadSites();
      },
    });
  }

  $("#add-group").addEventListener("click", addGroup);
  // the group the drawer is filtered to comes pre-selected; otherwise "Diğer" (no group)
  $("#add-site").addEventListener("click", () => {
    const g = state.groups.find((x) => groupKey(x.id) === state.groupFilter);
    openAdd(g ? g.id : null);
  });

  // ---- drag and drop ordering. Pointer events, so the same code serves mouse, pen and touch:
  // mouse drags after a few pixels; touch drags at once in edit mode, otherwise after a long press
  // (so an ordinary swipe still scrolls the page). The tile follows the finger and the others make
  // room with a short slide; the new order (and group) is saved when the tile is let go.
  const drag = { tile: null, pending: null, suppressClick: false };
  const HOLD_MS = 380, SLOP = 6;

  function tileRects(box) {
    return new Map([...box.querySelectorAll(".site[data-id]")].map((t) => [t, t.getBoundingClientRect()]));
  }

  // slide every tile from where it was to where it is now (FLIP)
  function animateFrom(before) {
    for (const [t, r] of before) {
      if (t === drag.tile) continue;
      const now = t.getBoundingClientRect();
      const dx = r.left - now.left, dy = r.top - now.top;
      if (!dx && !dy) continue;
      t.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
        { duration: 180, easing: "cubic-bezier(.2, 0, .2, 1)" });
    }
  }

  function follow(x, y) {
    const t = drag.tile;
    t.style.transform = "none";
    const r = t.getBoundingClientRect();
    t.style.transform = `translate(${x - drag.grabX - r.left}px, ${y - drag.grabY - r.top}px) scale(1.04)`;
  }

  const pageRect = (el) => {
    const b = el.getBoundingClientRect();
    return { left: b.left + scrollX, top: b.top + scrollY, right: b.right + scrollX, bottom: b.bottom + scrollY };
  };
  const gridOrders = () => new Map([...$("#sites").querySelectorAll(".sites-grid")].map((g) =>
    [g.dataset.group, [...g.querySelectorAll(".site[data-id]")].map((t) => Number(t.dataset.id))]));

  // The drop targets, in page coordinates, measured once when the drag starts. The target is the slot
  // under the finger, never "the tile under the finger" — a neighbour sliding out of the way would
  // pass under the finger again and swap straight back, which made the tiles shake.
  // Only the tile's own group reorders live (its size never changes). Over another group nothing moves
  // until the drop — a marker shows where the tile will land — because moving a tile into another
  // group changes both groups' heights, shifts everything below, and puts a different slot under a
  // finger that did not move: that made the tiles jump back and forth.
  function measure() {
    const box = $("#sites");
    drag.slots = [...box.querySelectorAll(".site[data-id]")].map((el) => ({ el, grid: el.parentNode, ...pageRect(el) }));
    // a group's title (also of a collapsed group) and a grid with no store take the tile at its end
    drag.zones = [...box.querySelectorAll(".site-group")].flatMap((sec) => {
      const g = sec.querySelector(".sites-grid");
      const out = [{ group: sec.dataset.group, ...pageRect(sec.querySelector(".group-head")) }];
      if (g && !g.querySelector(".site[data-id]")) out.push({ group: sec.dataset.group, ...pageRect(g) });
      else if (g) out.push({ group: sec.dataset.group, ...pageRect(g) });   // the gaps of a group: its end
      return out;
    });
  }

  function startDrag(p) {
    const t = p.tile, r = t.getBoundingClientRect();
    drag.tile = t;
    drag.grabX = p.x - r.left;
    drag.grabY = p.y - r.top;
    drag.startOrders = gridOrders();
    drag.drop = null;
    measure();
    t.classList.add("dragging");
    $("#sites").classList.add("sorting");
    if (navigator.vibrate) navigator.vibrate(12);
    follow(p.x, p.y);
  }

  const inside = (s, px, py, inset = 0.15) => {
    const mx = (s.right - s.left) * inset, my = (s.bottom - s.top) * inset;
    return px > s.left + mx && px < s.right - mx && py > s.top + my && py < s.bottom - my;
  };

  function clearMarks() {
    $("#sites").querySelectorAll(".drop, .drop-before, .drop-after").forEach((el) => el.classList.remove("drop", "drop-before", "drop-after"));
  }

  // where the tile would land in another group: { group, el, after } (el null = at the end)
  function markDrop(drop) {
    const same = drag.drop && drop && drag.drop.group === drop.group && drag.drop.el === drop.el && drag.drop.after === drop.after;
    if (same || (!drag.drop && !drop)) return;
    clearMarks();
    drag.drop = drop;
    if (!drop) return;
    $("#sites").querySelector(`.site-group[data-group="${drop.group}"]`)?.classList.add("drop");
    if (drop.el) drop.el.classList.add(drop.after ? "drop-after" : "drop-before");
  }

  function moveDrag(x, y) {
    follow(x, y);
    const px = x + scrollX, py = y + scrollY;
    const own = drag.tile.parentNode;
    // only the inner part of a slot counts, so resting on the line between two slots does nothing
    const slot = drag.slots.find((s) => inside(s, px, py));
    if (slot && slot.grid === own) {
      markDrop(null);
      if (slot.el === drag.tile) return;
      const box = $("#sites"), before = tileRects(box);
      const tiles = [...own.querySelectorAll(".site[data-id]")];
      own.insertBefore(drag.tile, tiles.indexOf(slot.el) > tiles.indexOf(drag.tile) ? slot.el.nextSibling : slot.el);
      follow(x, y);
      animateFrom(before);
      return;
    }
    if (slot) {                                         // a tile of another group: before or after it
      markDrop({ group: slot.grid.dataset.group, el: slot.el, after: px > (slot.left + slot.right) / 2 });
      return;
    }
    // a group's title or the empty part of a group: its end (its own group's gaps change nothing)
    const zone = drag.zones.find((z) => inside(z, px, py, 0));
    const ownGroup = own.dataset.group;
    markDrop(zone && zone.group !== ownGroup ? { group: zone.group, el: null, after: false } : null);
  }

  async function endDrag(cancelled) {
    const t = drag.tile, drop = drag.drop;
    drag.tile = null;
    drag.drop = null;
    const box = $("#sites");
    box.classList.remove("sorting");
    clearMarks();
    t.classList.remove("dragging");
    t.style.transform = "";
    drag.suppressClick = true;                       // the click that follows a drop must not open the site
    setTimeout(() => { drag.suppressClick = false; }, 400);
    if (cancelled) { renderSites(); return; }
    const orders = gridOrders();
    const id = Number(t.dataset.id);
    if (drop) {
      for (const ids of orders.values()) { const i = ids.indexOf(id); if (i >= 0) ids.splice(i, 1); }
      if (!orders.has(drop.group)) {                 // a collapsed group: its stores are not on the page
        orders.set(drop.group, state.sites.filter((s) => groupKey(s.group_id) === drop.group && s.id !== id).map((s) => s.id));
      }
      const ids = orders.get(drop.group);
      const at = drop.el ? ids.indexOf(Number(drop.el.dataset.id)) + (drop.after ? 1 : 0) : ids.length;
      ids.splice(at < 0 ? ids.length : at, 0, id);
    }
    const changed = [...orders].filter(([g, ids]) => (drag.startOrders.get(g) || []).join() !== ids.join());
    if (!changed.length) { renderSites(); return; }
    saveGroups(changed);
  }

  async function saveGroups(changed) {
    const byId = new Map(state.sites.map((s) => [s.id, s]));
    for (const [g, ids] of changed) ids.forEach((id) => { byId.get(id).group_id = g === "" ? null : Number(g); });
    renderSites();
    try {
      for (const [g, ids] of changed) {
        // a collapsed group's grid is not on the page: send its whole membership, kept in order
        await api("/api/sites/order", { method: "PUT", body: { ids, group_id: g === "" ? null : Number(g), regroup: true } });
      }
      await loadSites();                               // canonical order, and "Sitelerde ara" follows it
    } catch (e) {
      toast(`Sıralama kaydedilemedi: ${e.message}`);
      loadSites();
    }
  }

  // keyboard: in edit mode, arrow keys move the focused tile within its group
  function keyMove(e, tile) {
    if (!state.editing || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const grid = tile.parentNode, before = tileRects($("#sites"));
    const back = e.key === "ArrowLeft" || e.key === "ArrowUp";
    const sib = back ? tile.previousElementSibling : tile.nextElementSibling;
    if (!sib || !sib.dataset.id) return;
    grid.insertBefore(tile, back ? sib : sib.nextSibling);
    animateFrom(before);
    tile.focus();
    const ids = [...grid.querySelectorAll(".site[data-id]")].map((t) => Number(t.dataset.id));
    api("/api/sites/order", { method: "PUT", body: { ids, group_id: grid.dataset.group === "" ? null : Number(grid.dataset.group), regroup: true } })
      .then(loadSites, (err) => toast(err.message));
  }

  const sitesBox = $("#sites");
  sitesBox.addEventListener("pointerdown", (e) => {
    const tile = e.target.closest(".site[data-id]");
    if (!tile || e.target.closest(".tools, .site-del") || e.button > 0 || drag.tile) return;
    const p = { tile, x: e.clientX, y: e.clientY, id: e.pointerId, type: e.pointerType, timer: null };
    drag.pending = p;
    if (e.pointerType !== "mouse") {
      if (state.editing) { e.preventDefault(); startDrag(p); }
      else p.timer = setTimeout(() => { if (drag.pending === p) startDrag(p); }, HOLD_MS);
    }
  });
  addEventListener("pointermove", (e) => {
    const p = drag.pending;
    if (!p || e.pointerId !== p.id) return;
    if (drag.tile) { e.preventDefault(); moveDrag(e.clientX, e.clientY); return; }
    const far = Math.hypot(e.clientX - p.x, e.clientY - p.y) > SLOP;
    if (!far) return;
    if (p.type === "mouse") { startDrag(p); moveDrag(e.clientX, e.clientY); }
    else { clearTimeout(p.timer); drag.pending = null; }   // a swipe before the long press: let it scroll
  }, { passive: false });
  const finish = (cancelled) => (e) => {
    const p = drag.pending;
    if (!p || e.pointerId !== p.id) return;
    clearTimeout(p.timer);
    drag.pending = null;
    if (drag.tile) endDrag(cancelled);
  };
  addEventListener("pointerup", finish(false));
  addEventListener("pointercancel", finish(true));
  // while a tile is held, the finger moves the tile, not the page
  addEventListener("touchmove", (e) => { if (drag.tile) e.preventDefault(); }, { passive: false });
  sitesBox.addEventListener("contextmenu", (e) => { if (drag.tile || drag.pending) e.preventDefault(); });

  async function renameSite(s) {
    const name = prompt("Site adı", s.name);
    if (!name || name.trim() === s.name) return;
    try { await api(`/api/sites/${s.id}`, { method: "PATCH", body: { name } }); await loadSites(); }
    catch (e) { toast(e.message); }
  }

  async function refreshLogo(s, tile) {
    tile.classList.add("busy");
    try { await api(`/api/sites/${s.id}/logo`, { method: "POST" }); await loadSites(); toast("Logo yenilendi"); }
    catch (e) { tile.classList.remove("busy"); toast(e.message); }
  }

  function removeSite(s, tile) {
    const inDock = () => document.querySelector(`#dock a[data-id="${s.id}"]`);
    undoable(`${s.name} kaldırıldı`, {
      el: tile,
      hide: () => { const d = inDock(); if (d) d.hidden = true; },
      restore: () => { const d = inDock(); if (d) d.hidden = false; },
      commit: async () => { await api(`/api/sites/${s.id}`, { method: "DELETE" }); await loadSites(); },
    });
  }

  function openAdd(gid = null) {
    const sel = $("#add-group-select");
    fill(sel, h("option", { value: "" }, "Diğer (grupsuz)"),
      ...state.groups.map((g) => h("option", { value: g.id }, g.name)));
    sel.value = gid == null ? "" : String(gid);
    sel.hidden = $("#add-group-label").hidden = !state.groups.length;
    $("#add-url").value = "";
    $("#add-error").hidden = true;
    $("#add-submit").disabled = false;
    $("#add-submit").textContent = "Ekle";
    $("#add-dialog").showModal();
    $("#add-url").focus();
  }

  $("#add-cancel").addEventListener("click", () => $("#add-dialog").close());
  $("#add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#add-submit");
    btn.disabled = true;
    btn.textContent = "Ekleniyor…";
    try {
      const gsel = $("#add-group-select").value;
      const s = await api("/api/sites", { method: "POST", body: { url: $("#add-url").value, group_id: gsel ? Number(gsel) : null } });
      $("#add-dialog").close();
      await loadSites();
      toast(s.logo ? `${s.name} eklendi` : `${s.name} eklendi (logo bulunamadı)`);
    } catch (err) {
      $("#add-error").textContent = err.message;
      $("#add-error").hidden = false;
      btn.disabled = false;
      btn.textContent = "Ekle";
    }
  });

  // the stores drawer is always the editor (rename, remove, reorder, groups): every change is saved
  // the moment it is made, so there is no "Bitti"
  function setEditing(on) {
    if (state.editing === on) return;
    state.editing = on;
    renderSites();
  }

  // ------------------------------------------------------------ search
  // scope: "all", "mine" (every store of mine) or "mine:<group>" (one group, picked next to "Sitelerim")
  function setScope(scope) {
    if (scope.startsWith("mine:") && !state.groups.some((g) => `mine:${g.id}` === scope) && state.groups.length) scope = "mine";
    state.scope = scope;
    try { localStorage.setItem("commerce_scope", scope); } catch (_) { /* private mode */ }
    if (state.cart.items.length && state.cart.result && state.cart.result.scope !== scope) loadCart();
  }

  // which stores a result shows: in the result's toolbar, not before the search (it only filters)
  function scopeControl() {
    const kind = state.scope.startsWith("mine") ? "mine" : "all";
    const pick = (k) => {
      if (kind === k) return;
      setScope(k === "mine" ? (state.mineScope || "mine") : "all");
      rescope();
    };
    return h("span", { class: "scope-ctl" },
      h("span", { class: "seg sm", role: "radiogroup", "aria-label": "Hangi mağazalar" },
        [["all", "Tüm mağazalar"], ["mine", "Sitelerim"]].map(([k, label]) =>
          h("button", { type: "button", role: "radio", "aria-checked": String(kind === k), onclick: () => pick(k) }, label))),
      state.groups.length && kind === "mine" ? h("select", { class: "scope-group", "aria-label": "Hangi sitelerim",
        onchange: (e) => { state.mineScope = e.target.value; setScope(e.target.value); rescope(); } },
        h("option", { value: "mine" }, "Tüm sitelerim"),
        state.groups.map((g) => h("option", { value: `mine:${g.id}`, selected: state.scope === `mine:${g.id}` }, g.name))) : null);
  }

  // the result on screen, filtered again for the chosen stores from its stored search: no new request
  async function rescope() {
    const r = state.result;
    if (!r || !r.id) { if (r) renderResult(r); return; }
    try {
      const next = await api(`/api/history/${r.id}?scope=${encodeURIComponent(state.scope)}`);
      state.result = dict(next, r);
      renderResult(state.result);
    } catch (e) { toast(e.message); }
  }
  // keep how the result was reached (fresh or from history), whatever the refilter says
  const dict = (next, prev) => Object.assign(next, { from_cache: prev.from_cache });


  const currentProduct = () => {
    const r = state.result;
    if (!r || !r.product || !r.products || !r.products.length) return "";
    return r.product.path === r.products[0].path ? "" : r.product.path;
  };

  // ------------------------------------------------------------ search box: examples type themselves while it is empty
  (() => {
    const EXAMPLES = ["AirPods Pro 2", "Dyson V15", "kablosuz kulaklık", "Logitech MX Keys", "bluetooth hoparlör",
      "robot süpürge", "airfryer", "spor ayakkabı"];
    const input = $("#q"), box = input.closest(".search-box"), out = box.querySelector(".typer b");
    const lens = box.querySelector("svg");
    const calm = matchMedia("(prefers-reduced-motion: reduce)");
    let timer = null, word = 0, len = 0, deleting = false;
    const can = () => !input.value && document.activeElement !== input && !document.hidden && !calm.matches;
    function stop() {
      clearTimeout(timer);
      timer = null;
      box.classList.remove("typing");
      out.textContent = "";
    }
    function tick() {
      if (!can()) { stop(); return; }
      const w = EXAMPLES[word];
      if (!deleting) {
        out.textContent = w.slice(0, ++len);
        if (len === w.length) { deleting = true; timer = setTimeout(tick, 1400); return; }
        timer = setTimeout(tick, 70 + Math.random() * 60);
        return;
      }
      out.textContent = w.slice(0, --len);
      if (len > 0) { timer = setTimeout(tick, 35); return; }
      deleting = false;
      word = (word + 1) % EXAMPLES.length;
      lens.classList.remove("lens-wiggle");
      void lens.getBoundingClientRect();          // restart the wiggle
      lens.classList.add("lens-wiggle");
      timer = setTimeout(tick, 350);
    }
    function start() {
      if (timer || !can()) return;
      len = 0;
      deleting = false;
      box.classList.add("typing");
      timer = setTimeout(tick, 400);
    }
    input.addEventListener("focus", stop);
    input.addEventListener("input", stop);
    input.addEventListener("blur", () => { if (!input.value) { word = (word + 1) % EXAMPLES.length; start(); } });
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));
    calm.addEventListener("change", () => (calm.matches ? stop() : start()));
    state.typerStart = start;
    start();
  })();

  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#q").value.trim();
    if (q.length >= 2) quick(q);
  });

  // while results are open the store strip steps aside, so the offers sit higher
  function showResults() {
    $("#results").hidden = false;
    $("#welcome").hidden = true;
    document.body.classList.add("has-results");
  }

  // "⋯ → Kapat": the result goes away and the welcome comes back (the search stays in the history)
  function closeResults() {
    state.result = null;
    state.trackOpen = false;
    fill($("#results"));
    $("#results").hidden = true;
    $("#welcome").hidden = false;
    document.body.classList.remove("has-results");
  }

  // the shape of a result while it loads: header, model strip, three cards
  function showLoading(text) {
    showResults();
    const bar = (w) => h("span", { class: "sk sk-bar", style: `width:${w}` });
    fill($("#results"), h("div", { class: "loading-sk", "aria-busy": "true" },
      h("div", { class: "loading" }, h("span", { class: "spinner" }), text),
      h("div", { class: "sk-head" }, h("span", { class: "sk sk-img" }), h("span", { class: "sk-lines" }, bar("60%"), bar("30%"))),
      h("div", { class: "sk-strip" }, [1, 2, 3, 4].map(() => h("span", { class: "sk sk-chip" }))),
      h("div", { class: "sk-cards" }, [1, 2, 3].map(() => h("span", { class: "sk sk-card" })))));
  }

  async function quick(q, { product = "", refresh = false, quiet = false } = {}) {
    if (state.busy) return;
    state.busy = "quick";
    state.query = q;
    renderHealth();
    if (!quiet) showLoading("Fiyatlar aranıyor…");
    const p = new URLSearchParams({ q, scope: state.scope });
    if (product) p.set("product", product);
    if (refresh) p.set("refresh", "1");
    try {
      state.result = await api(`/api/search?${p}`);
      renderResult(state.result);
      loadHistory();
    } catch (e) {
      state.result = null;
      renderError(q, e.message);
    } finally {
      state.busy = false;
      loadStatus();
    }
  }

  async function deep(q, refresh = false) {
    if (state.busy) return;
    state.busy = "deep";
    state.query = q;
    renderHealth();
    showLoading("Yapay zekâ internette arıyor… (10-30 sn)");
    try {
      state.result = await api("/api/search/deep", { method: "POST", body: { q, scope: state.scope, refresh } });
      renderResult(state.result);
      loadHistory();
    } catch (e) {
      state.result = null;
      renderError(q, e.message, true);
    } finally {
      state.busy = false;
      loadStatus();
    }
  }

  function renderError(q, msg, wasDeep = false) {
    const box = $("#results");
    showResults();
    fill(box, 
      h("div", { class: "res-head" }, h("h2", {}, q)),
      h("div", { class: "notice" }, msg,
        wasDeep ? null : h("button", { class: "btn sm deep", type: "button", onclick: () => deep(q) }, "Derin ara")),
      wasDeep ? null : tryInstead(q),
      siteLinks(q));
  }

  // nothing found: shorter versions of the query (one word left out each), and what tends to work
  function tryInstead(q) {
    const words = q.split(/\s+/).filter(Boolean);
    const shorter = words.length < 2 ? [] : [...new Set(words.map((_, i) => words.filter((__, j) => j !== i).join(" ")))]
      .filter((s) => s.length >= 2).slice(0, 4);
    return h("div", { class: "try-instead" },
      shorter.length ? h("div", { class: "ti-row" }, h("span", { class: "muted small" }, "Şunu dene:"),
        shorter.map((s) => h("button", { class: "chip", type: "button", onclick: () => { $("#q").value = s; quick(s); } }, s))) : null,
      h("p", { class: "muted small" }, "İpucu: marka + model (\"Dyson V15\") ya da marka + ürün türü (\"Hunter bot\") en iyi sonucu verir; renk ve beden gibi ayrıntıları sonra filtrele."));
  }

  function scopeLabel(scope) {
    if (scope === "mine") return "Sitelerim";
    const g = state.groups.find((x) => `mine:${x.id}` === scope);
    return g ? `Sitelerim › ${g.name}` : "Sitelerim";
  }

  function deepButton(q, label = "Derin ara") {
    return h("button", { class: "btn sm deep", type: "button", title: "Yapay zekâ + web araması (token harcar)", onclick: () => deep(q) }, label);
  }

  function renderResult(r) {
    const box = $("#results");
    showResults();
    const isDeep = r.kind === "deep";
    const title = (!isDeep && r.product && r.product.title) || r.query;
    const meta = [isDeep ? `Derin · ${fmtTokens(r.tokens)} token` : "Hızlı · token yok",
      r.from_cache && r.created_at ? `kayıtlı ${ago(r.created_at)}` : null].filter(Boolean).join(" · ");
    const canTrack = !isDeep && r.product && r.offers;
    const picked = !isDeep && r.product ? (r.products || []).find((x) => x.path === r.product.path) : null;
    // tracking as an icon, the rest in "⋯"; adding to the cart is on each store's offer below
    const actions = h("div", { class: "actions" },
      canTrack ? h("span", { class: "track-anchor" },
        h("button", { class: "icon-act" + (r.tracked_id ? " on" : ""), type: "button",
          "data-tip": r.tracked_id ? "Takipte" : "Takibe al", "aria-expanded": r.tracked_id ? null : String(!!state.trackOpen),
          "aria-label": r.tracked_id ? "Fiyat takibinde — takip listesine git" : "Takibe al: fiyat düşünce haber ver (token yok)",
          onclick: () => {
            if (r.tracked_id) { showPanel("track"); return; }
            state.trackOpen = !state.trackOpen;
            renderResult(r);
          } }, icon("bell")),
        state.trackOpen && !r.tracked_id ? trackPop(r, picked) : null) : null,
      isDeep ? h("button", { class: "btn sm", type: "button", onclick: () => quick(r.query) }, "Hızlı sonuç") : null,
      moreMenu([{ label: isDeep ? "Yenile (token harcar)" : "Fiyatları yenile",
        run: () => (isDeep ? deep(r.query, true) : quick(r.query, { product: currentProduct(), refresh: true })) },
        { label: "Kapat", run: closeResults }]));
    const parts = [h("div", { class: "res-head" }, productImg(picked && picked.image, "head-img"),
      h("div", { class: "res-title" }, h("h2", {}, title), h("span", { class: "res-meta" }, meta, priceCheck(r.price_check))), actions)];

    if (isDeep && r.summary) parts.push(h("p", { class: "summary" }, r.summary));
    if (r.source) {   // fewer stores than usual answered: a deeper search may find more
      parts.push(h("div", { class: "notice" }, "Bu arama için sınırlı sayıda mağazadan sonuç bulundu.", deepButton(r.query)));
    }

    if (!isDeep && r.products && r.products.length > 1) {
      parts.push(h("div", { class: "products", role: "list", "aria-label": "Bulunan ürünler" },
        r.products.map((p) => h("button", {
          class: "product", type: "button", role: "listitem", "aria-pressed": String(r.product && p.path === r.product.path),
          onclick: () => { if (!r.product || p.path !== r.product.path) quick(r.query, { product: p.path === r.products[0].path ? "" : p.path }); },
        }, p.image ? h("img", { src: p.image, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("span"),
          h("span", { class: "pt" }, h("span", { class: "pn", title: p.name }, p.name),
            h("span", { class: "pp" }, p.price ? h("b", {}, fmtPrice(p.price)) : "—", ` · ${p.offers} satıcı`))))));
    }

    if (r.empty) {
      parts.push(h("div", { class: "notice" }, "Bu aramayla ürün bulunamadı.", deepButton(r.query, "Derin ara")), tryInstead(r.query));
    } else if (!r.offers.length) {
      const msg = r.scope !== "all" && r.total_offers
        ? `Sitelerinde bu ürün için teklif yok (internette ${r.total_offers} teklif var).`
        : "Teklif bulunamadı.";
      parts.push(h("div", { class: "notice" }, msg,
        r.scope !== "all" && r.total_offers ? h("button", { class: "btn sm", type: "button", onclick: () => { setScope("all"); rescope(); } }, "Tüm mağazaları göster") : null,
        !isDeep ? deepButton(r.query) : null));
    } else {
      // the first three as cards, the rest as a compact list; scope, filters and sort apply to both
      const shown = sortOffers(isDeep ? r.offers : r.offers.filter(passes));
      parts.push(resultToolbar(r.offers, shown, isDeep));
      if (!shown.length) parts.push(h("div", { class: "empty" }, "Seçili filtrelere uyan teklif yok."));
      else {
        // "En ucuz" goes with the price, wherever the chosen sort puts it
        const cheapest = shown.reduce((m, o) => (o.price < m.price ? o : m), shown[0]);
        // each offer has its own 🛒: buy from that store
        const perOffer = !isDeep;
        parts.push(h("div", { class: "top-offers" }, shown.slice(0, 3).map((o) => withCart(offerCard(o, o === cheapest, isDeep), o, perOffer))));
        const rest = shown.slice(3);
        if (rest.length) {
          parts.push(h("div", { class: "more-head" }, `+ ${rest.length} teklif daha`));
          parts.push(h("ol", { class: "offers compact" }, rest.map((o) => withCart(offerRow(o, o === cheapest, isDeep), o, perOffer))));
        }
      }
      // the deep search, once, where someone who did not find it looks next
      if (!isDeep && !r.source) {
        parts.push(h("div", { class: "deep-hint" }, "Bulamadın mı? ", deepButton(r.query),
          h("span", { class: "muted small" }, "Yapay zekâ + web araması ile tüm internet (token harcar)")));
      }
    }

    if (isDeep && r.sources && r.sources.length) {
      parts.push(h("div", { class: "sources" }, "Kaynaklar: ",
        r.sources.map((s) => h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title))));
    }
    parts.push(siteLinks(r.query));
    fill(box, ...parts);
  }

  // "is this a good price?": the cheapest offer now against what earlier searches and checks saw
  function priceCheck(c) {
    if (!c) return null;
    const since = `son ${c.days} günde`;
    const [cls, text] = {
      lowest: ["good", `${since}ki en düşük fiyat`],
      below: ["good", `ortalamanın %${Math.abs(c.pct)} altında`],
      typical: ["", "her zamanki fiyatı"],
      above: ["bad", `ortalamanın %${c.pct} üstünde`],
    }[c.verdict];
    return h("span", { class: "price-check " + cls,
      title: `${since} ${c.points} gün fiyat görüldü: en düşük ${fmtPrice(c.low)}, ortalama ${fmtPrice(c.avg)} (önceki aramalar ve fiyat takibi)` },
      c.verdict === "lowest" || c.verdict === "below" ? "▼ " : c.verdict === "above" ? "▲ " : "", text);
  }

  // ---- sort (remembered on this device)
  const SORTS = {
    price: { label: "En ucuz", cmp: (a, b) => a.price - b.price },
    rating: { label: "En yüksek puan", cmp: (a, b) => (b.rating ?? -1) - (a.rating ?? -1) || a.price - b.price },
    fast: { label: "En hızlı kargo", cmp: (a, b) => speed(a) - speed(b) || a.price - b.price },
  };
  const speed = (o) => (/bugün/i.test(o.delivery || "") ? 0 : /yarın/i.test(o.delivery || "") ? 1 : 2);
  try { state.sort = SORTS[localStorage.getItem("commerce_sort")] ? localStorage.getItem("commerce_sort") : "price"; }
  catch (_) { state.sort = "price"; }
  const sortOffers = (list) => [...list].sort(SORTS[state.sort].cmp);

  // scope, filters, sort: one row above the offers
  function resultToolbar(all, shown, isDeep) {
    const hidden = all.length - shown.length;
    return h("div", { class: "filters" },
      scopeControl(),
      isDeep ? null : h("span", { class: "filter-chips", role: "group", "aria-label": "Teklif filtreleri" },
        FILTERS.map((f) => h("button", {
          class: "chip", type: "button", "aria-pressed": String(state.filters.has(f.key)), title: f.title || null,
          onclick: () => {
            state.filters.has(f.key) ? state.filters.delete(f.key) : state.filters.add(f.key);
            try { localStorage.setItem("commerce_filters", [...state.filters].join(",")); } catch (_) { /* private mode */ }
            renderResult(state.result);
          },
        }, f.label))),
      hidden ? h("span", { class: "muted small" }, `${hidden} teklif gizlendi`) : null,
      h("label", { class: "sort" }, h("span", { class: "muted small" }, "Sırala"),
        h("select", { "aria-label": "Teklifleri sırala", onchange: (e) => {
          state.sort = e.target.value;
          try { localStorage.setItem("commerce_sort", state.sort); } catch (_) { /* private mode */ }
          renderResult(state.result);
        } }, Object.entries(SORTS).map(([k, s]) => h("option", { value: k, selected: state.sort === k }, s.label)))));
  }

  // "⋯": the less used actions of a result
  function moreMenu(items) {
    const list = h("div", { class: "menu-pop", role: "menu", hidden: true });
    const btn = h("button", { class: "icon-act", type: "button", "data-tip": "Diğer", "aria-label": "Diğer işlemler",
      "aria-haspopup": "menu", "aria-expanded": "false",
      onclick: (e) => {
        e.stopPropagation();
        list.hidden = !list.hidden;
        btn.setAttribute("aria-expanded", String(!list.hidden));
        if (!list.hidden) list.querySelector("button")?.focus();
      } }, icon("dots"));
    fill(list, ...items.map((it) => h("button", { type: "button", role: "menuitem",
      onclick: () => { list.hidden = true; btn.setAttribute("aria-expanded", "false"); it.run(); } }, it.label)));
    return h("span", { class: "more-menu" }, btn, list);
  }
  const closeMenus = () => document.querySelectorAll(".menu-pop:not([hidden])").forEach((m) => {
    m.hidden = true;
    m.previousElementSibling?.setAttribute("aria-expanded", "false");
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".more-menu")) closeMenus(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

  // ---- offer filters (quick results; remembered on this device)
  const FILTERS = [
    { key: "stock", label: "Stokta", title: "Stokta olduğunu söyleyen teklifler",
      test: (o) => !!o.stock && /^stokta/i.test(o.stock) && !/yok|tükendi/i.test(o.stock) },
    { key: "ship", label: "Ücretsiz kargo", test: (o) => !!o.free_shipping },
    { key: "fast", label: "Hızlı kargo", title: "Bugün ya da yarın kargoda", test: (o) => /bugün|yarın/i.test(o.delivery || "") },
    { key: "rated", label: "Puanı düşükleri gizle", title: "Puanı 7'nin altındaki mağazaları gizler (puanı olmayanlar kalır)",
      test: (o) => o.rating == null || o.rating >= 7 },
  ];
  const passes = (o) => FILTERS.every((f) => !state.filters.has(f.key) || f.test(o));



  // a product picture from the store's image server: lazy, no referrer; a broken one just goes away
  function productImg(src, cls) {
    if (!src || !/^https:\/\//.test(src)) return null;
    // MediaMarkt hands out originals (1-2k px): ask its image server for a small one, as its own site does
    if (/^https:\/\/assets\.mmsrg\.com\/[^?]+$/.test(src))
      src += "?x=160&y=160&format=webp&quality=70&sp=yes&strip=yes&trim=yes&ex=160&ey=160&align=center&resizesource";
    return h("img", { class: "pimg " + cls, src, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer",
      onerror: (e) => { const box = e.target.closest(".has-img"); if (box) box.classList.remove("has-img"); e.target.remove(); } });
  }

  // a 🛒 icon on one store's offer: in the card's top-right corner (beside the link, not inside it),
  // at the end of a list row; its label shows on hover
  function withCart(el, o, on) {
    if (!on || !o.url) return el;
    const product = state.result.product ? state.result.product.path : null;
    const inCart = offerInCart(o.url, product);
    const tip = inCart ? "Sepette" : product && productInCart(product) ? "Bu mağazadan al" : "Sepete ekle";
    const btn = h("button", { class: "offer-cart" + (inCart ? " in-cart" : ""), type: "button", "data-tip": tip,
      "aria-label": `${o.title || o.store}: ${tip.toLocaleLowerCase("tr-TR")}`,
      onclick: async () => {
        if (inCart) { showPanel("cart"); return; }
        // the main source gives no picture per offer: the product's own picture stands in
        const pic = (state.result.products || []).find((p) => p.path === product);
        await addToCart(o.url, o.title || state.result.query, o.image || (pic && pic.image), product);
      } }, icon(inCart ? "check" : "cart"));
    if (el.tagName === "LI") { el.classList.add("has-cart"); el.append(btn); return el; }
    return h("div", { class: "ocard-wrap" }, el, btn);
  }

  // the cart line holding this result's product: picked at one of its stores, or added as the product
  const productInCart = (product) => state.cart.items.find((i) => i.product === product || i.path === product);

  // is this store's offer the one in the cart? A line added as the product (from the tracked list)
  // is bought where the cart's split puts it
  function offerInCart(url, product) {
    if (state.cart.items.some((i) => i.path === url)) return true;
    const line = product && state.cart.items.find((i) => i.path === product);
    if (!line || !state.cart.result) return false;
    return state.cart.result.orders.some((ord) => ord.items.some((p) => p.id === line.id && p.url === url));
  }

  // one of the three cheapest offers; the whole card opens the seller
  function offerCard(o, best, approx) {
    const site = o.site_id ? siteById(o.site_id) : null;
    const meta = [
      o.free_shipping ? h("span", { class: "ok" }, "Ücretsiz kargo") : null,
      o.delivery ? h("span", {}, o.delivery) : null,
      o.stock && !o.delivery ? h("span", {}, o.stock) : null,
      o.rating != null ? h("span", { class: o.rating < 7 ? "down" : "", title: `Mağaza puanı (${o.reviews || 0} yorum)` }, `★ ${o.rating.toLocaleString("tr-TR")}`) : null,
      o.note ? h("span", {}, o.note) : null,
    ].filter(Boolean);
    const img = productImg(o.image, "o-img");
    return h(o.url ? "a" : "div", {
      class: "ocard" + (best ? " best" : "") + (img ? " has-img" : ""), href: o.url || null, target: o.url ? "_blank" : null,
      rel: o.url ? "noopener noreferrer" : null, title: `${site ? site.name : o.store} sayfasını aç`,
    },
      img,
      // no "Sitem" tag on the big cards: it was squeezed to an "S" beside the corner icon
      h("div", { class: "o-store" }, logo(site, o.store), h("span", {}, site ? site.name : o.store)),
      h("div", { class: "o-price" }, approx ? "≈ " : "", fmtPrice(o.price, o.currency)),
      best || approx ? h("div", { class: "o-tag" + (approx ? " approx" : "") }, approx ? (best ? "Yaklaşık · en ucuz" : "Yaklaşık") : "En ucuz") : null,
      meta.length ? h("div", { class: "o-meta" }, meta) : null,
      o.title ? h("div", { class: "o-title", title: o.title }, o.seller ? `${o.seller} · ${o.title}` : o.title) : null);
  }

  function offerRow(o, best, approx) {
    const site = o.site_id ? siteById(o.site_id) : null;
    const extra = [
      o.rating != null ? h("span", { class: "rating" + (o.rating < 7 ? " low" : ""), title: `Mağaza puanı (${o.reviews || 0} yorum)` },
        `★ ${o.rating.toLocaleString("tr-TR")}`) : null,
      o.free_shipping ? h("span", { class: "ok" }, "Ücretsiz kargo") : null,
      o.stock ? h("span", {}, o.stock) : null,
      o.delivery ? h("span", {}, o.delivery) : null,
      o.note ? h("span", {}, o.note) : null,
      o.link_fallback ? h("span", { title: "Yapay zekânın verdiği ürün bağlantısı açılmadı; mağazada arama açılır" }, "Mağazada ara") : null,
    ].filter(Boolean);
    // the whole row opens the seller; Gemini prices are only an estimate, so they say so
    const row = o.url
      ? h("a", { class: "offer-row", href: o.url, target: "_blank", rel: "noopener noreferrer",
        title: `${site ? site.name : o.store} sayfasını aç` })
      : h("div", { class: "offer-row" });
    row.append(
      logo(site, o.store),
      (() => {
        const thumb = productImg(o.image, "row-img");
        return h("div", { class: "info" + (thumb ? " has-img" : "") }, thumb, h("div", { class: "info-text" },
          h("div", { class: "store" }, site ? site.name : o.store,
            o.seller ? h("span", { class: "seller" }, `/ ${o.seller}`) : null,
            site ? h("span", { class: "mine-tag" }, "Sitem") : null),
          o.title ? h("div", { class: "title", title: o.title }, o.title) : null,
          extra.length ? h("div", { class: "extra" }, extra) : null));
      })(),
      h("div", { class: "price" + (approx ? " approx" : "") },
        approx ? h("span", { class: "approx-mark", title: "Yapay zekânın bulduğu yaklaşık fiyat; sitede kontrol edin" }, "≈ ") : null,
        fmtPrice(o.price, o.currency),
        approx ? h("small", { class: "approx-label" }, best ? "Yaklaşık · en ucuz" : "Yaklaşık") : best ? h("small", {}, "En ucuz") : null),
      o.url ? h("span", { class: "btn sm go", "aria-hidden": "true" }, "Satıcıya git ↗") : h("span"));
    return h("li", { class: "offer" + (best ? " best" : "") }, row);
  }

  function siteLinks(q) {
    if (!state.sites.length) return null;
    return h("div", { class: "site-links" }, h("span", { class: "label" }, "Sitelerde ara:"),
      state.sites.map((s) => h("a", { class: "site-link", href: siteSearch(s, q), target: "_blank", rel: "noopener",
        title: s.own_search ? `${s.name} içinde ara` : `${s.name} içinde Google ile ara` }, logo(s), s.name)));
  }

  // ------------------------------------------------------------ orders (read from the stores' emails, no tokens)
  const ORDER_STATUS = {
    alindi: ["Sipariş alındı", ""], hazirlaniyor: ["Hazırlanıyor", ""], kargoda: ["Kargoda", "ship"],
    teslim: ["Teslim edildi", "free"], iptal: ["İptal", "stop"], iade: ["İade", "stop"],
  };
  state.orders = { state: null, items: [], archive: [] };
  state.orderSections = { past: false };
  state.orderOpen = new Set();          // orders whose email timeline is open

  async function loadOrders() {
    const before = new Map((state.orders.items || []).map((o) => [o.id, o]));
    try { state.orders = await api("/api/orders"); } catch (_) { return false; }
    renderOrders();
    // a scan started with the refresh button says what it found
    if (state.ordersAsked) {
      state.ordersAsked = false;
      const changed = state.orders.items.filter((o) => !before.has(o.id) || before.get(o.id).status !== o.status);
      const done = changed.filter((o) => before.has(o.id) && !o.open).length, added = changed.filter((o) => !before.has(o.id)).length;
      toast(state.orders.state && state.orders.state.error ? state.orders.state.error
        : !changed.length ? "E-postalar tarandı · yeni bir şey yok"
        : [added ? `${added} yeni sipariş` : null, done ? `${done} sipariş teslim edildi` : null,
          changed.length - added - done ? `${changed.length - added - done} sipariş güncellendi` : null].filter(Boolean).join(" · "));
    }
  }

  function renderOrdersMeta(o) {
    const parts = [];
    if (o.running) parts.push("taranıyor…");
    else if (o.error) parts.push(o.error);
    else if (o.last_scan) parts.push(`son tarama ${ago(o.last_scan)}`);
    $("#orders-meta").textContent = o.configured ? parts.join(" · ") : "";
    const btn = $("#orders-scan");
    btn.hidden = !o.configured;
    btn.disabled = o.running;
    btn.classList.toggle("busy", !!o.running);    // the arrow turns while the emails are read
    $("#tab-badge-orders").hidden = !o.open;
    $("#tab-badge-orders").textContent = String(o.open);
    // seen even with the card folded
    $("#orders-open").hidden = !o.open;
    $("#orders-open").textContent = `${o.open} aktif`;
  }

  function renderOrders() {
    const box = $("#orders"), { state: st, items } = state.orders, archive = state.orders.archive || [];
    if (st) renderOrdersMeta(st);
    const total = items.length + archive.length;
    $("#orders-count").textContent = total ? `${total} sipariş` : "";
    if (st && !st.configured && !items.length && !archive.length) {
      fill(box, h("div", { class: "setup" },
        h("p", { class: "muted" }, "Siparişlerini görmek için Gmail'i bağla. E-postalar yalnızca okunur, token harcanmaz."),
        h("button", { class: "btn sm primary", type: "button", "data-open-settings": "mail" }, icon("mail", 15), "E-posta bağla")));
      return;
    }
    if (!items.length && !archive.length) {
      fill(box, h("p", { class: "empty" }, st && st.last_scan ? "Sitelerinde sipariş yok." : "E-postalar ilk kez taranıyor…"));
      return;
    }
    // every closed order in one list, newest first: kept until the user deletes it, even when the
    // email is gone from Gmail
    const open = items.filter((o) => o.open), past = [...items.filter((o) => !o.open), ...archive];
    fill(box, ...open.map(orderRow),
      !open.length ? h("div", { class: "no-active" }, courier(), h("p", { class: "empty" }, "Aktif sipariş yok.")) : null,
      // starts closed; opened by the user, it stays open when the list is redrawn
      past.length ? h("details", { open: state.orderSections.past, ontoggle: (e) => { state.orderSections.past = e.target.open; } },
        h("summary", {}, `Geçmiş siparişler · ${past.length}`), ...past.map(orderRow)) : null);
  }

  // a courier riding on the spot while nothing is on its way (the road moves, not the scooter)
  const COURIER_SVG = `<svg viewBox="0 0 240 64" aria-hidden="true" focusable="false">
    <g class="c-speed"><line x1="52" y1="26" x2="76" y2="26"/><line x1="44" y1="36" x2="72" y2="36"/><line x1="56" y1="46" x2="78" y2="46"/></g>
    <g class="c-ride">
      <rect class="c-box" x="88" y="20" width="20" height="18" rx="3"/>
      <path class="c-box-line" d="M88 27h20"/>
      <path class="c-frame" d="M95 46h27l8-12h6l6 13"/>
      <path class="c-frame" d="M136 34l-4-13m-5 0h9"/>
      <path class="c-rider" d="M113 42l5-17m0 0l12 1m-17 14l9 2l1 6"/>
      <circle class="c-helmet" cx="120" cy="17" r="6"/>
      <g class="c-wheel" style="transform-origin:100px 50px"><circle cx="100" cy="50" r="8"/><path d="M100 42v16M92 50h16"/></g>
      <g class="c-wheel" style="transform-origin:142px 50px"><circle cx="142" cy="50" r="8"/><path d="M142 42v16M134 50h16"/></g>
    </g>
    <line class="c-road" x1="0" y1="60" x2="240" y2="60"/>
  </svg>`;
  // a shopping cart rolling along while a parcel keeps dropping into it
  const CART_SVG = `<svg viewBox="0 0 240 64" aria-hidden="true" focusable="false">
    <g class="c-speed"><line x1="50" y1="24" x2="74" y2="24"/><line x1="42" y1="34" x2="70" y2="34"/><line x1="54" y1="44" x2="76" y2="44"/></g>
    <g class="c-ride">
      <rect class="c-box c-drop" x="111" y="10" width="14" height="12" rx="2"/>
      <path class="c-frame" d="M80 12h9l5 9m0 0h54l-8 21h-40zm8 21l-3 6h42"/>
      <path class="c-box-line" d="M108 21l2 21m12-21v21m14-21l-2 21"/>
      <g class="c-wheel" style="transform-origin:104px 53px"><circle cx="104" cy="53" r="5"/><path d="M104 48v10M99 53h10"/></g>
      <g class="c-wheel" style="transform-origin:134px 53px"><circle cx="134" cy="53" r="5"/><path d="M134 48v10M129 53h10"/></g>
    </g>
    <line class="c-road" x1="0" y1="60" x2="240" y2="60"/>
  </svg>`;
  function emptyScene(svg) {
    const el = h("div", { class: "courier" });
    el.innerHTML = svg;   // a constant: no data goes into it
    return el;
  }
  const courier = () => emptyScene(COURIER_SVG);

  function orderRow(o) {
    const site = o.site_id ? siteById(o.site_id) : null;
    const [label, cls] = o.assumed ? ["Tamamlandı", "free"] : ORDER_STATUS[o.status] || [o.status, ""];
    const when = o.open ? o.ordered_at : (o.delivered_at || o.updated_at);
    const isOpen = state.orderOpen.has(o.id);
    return h("article", { class: "order-row" + (o.open ? "" : " closed") + (isOpen ? " show-tl" : "") },
      site ? logo(site) : h("span", { class: "logo" }),
      // the title opens the order's emails, oldest first
      h("button", { class: "o-title", type: "button", title: o.title || "", "aria-expanded": String(isOpen),
        onclick: () => { isOpen ? state.orderOpen.delete(o.id) : state.orderOpen.add(o.id); renderOrders(); } },
        o.title || "Sipariş", h("span", { class: "o-caret", "aria-hidden": "true" }, icon("chevron", 14))),
      h("div", { class: "o-meta" },
        h("span", { class: "badge " + cls, title: o.assumed ? "Teslim e-postası gelmedi; bir gün sonra kapatıldı" : null }, label),
        h("span", {}, site ? site.name : o.store),
        o.order_no ? h("span", { title: "Sipariş numarası" }, `#${o.order_no}`) : null,
        o.carrier ? h("span", {}, o.carrier) : null,
        h("span", { title: new Date(when).toLocaleString("tr-TR") }, ago(when))),
      o.total ? h("b", { class: "o-price" }, fmtPrice(o.total)) : null,
      h("div", { class: "o-actions" },
          // nothing left to follow once it has arrived (or was cancelled/returned)
          o.tracking_url && o.open ? h("a", { class: "btn sm", href: o.tracking_url, target: "_blank", rel: "noopener noreferrer" }, "Kargo takip ↗") : null,
          o.open ? h("button", { class: "btn sm ghost", type: "button", title: "Teslim aldım olarak işaretle", "aria-label": `${o.title || "Sipariş"}: teslim aldım`,
            onclick: (e) => markDelivered(o, e.currentTarget.closest(".order-row")) }, icon("check", 15)) : null,
          h("button", { class: "icon-btn", type: "button", title: "Sil", "aria-label": `${o.title || "Sipariş"} sil`,
            onclick: (e) => deleteOrder(o, e.currentTarget.closest(".order-row")) }, icon("x", 15))),
      isOpen ? orderTimeline(o) : null);
  }

  // what each email said, with its date; a closed-by-rule order says so at the end
  function orderTimeline(o) {
    const steps = (o.timeline || []).map((t) => {
      const [label] = ORDER_STATUS[t.status] || ["Bilgi e-postası"];
      return h("li", { class: t.status ? "" : "info" },
        h("span", { class: "tl-dot", "aria-hidden": "true" }),
        h("b", {}, t.status ? label : "Bilgi"),
        h("span", { class: "muted" }, new Date(t.received_at).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })),
        t.subject ? h("span", { class: "tl-subj", title: t.subject }, t.subject) : null);
    });
    if (o.assumed) steps.push(h("li", { class: "info" }, h("span", { class: "tl-dot", "aria-hidden": "true" }),
      h("b", {}, "Tamamlandı"), h("span", { class: "muted" }, "teslim e-postası gelmedi; bir gün sonra kapatıldı")));
    if (o.manual) steps.push(h("li", {}, h("span", { class: "tl-dot", "aria-hidden": "true" }), h("b", {}, "Teslim aldım"),
      h("span", { class: "muted" }, "elle işaretlendi")));
    return h("ol", { class: "o-timeline" }, steps.length ? steps : h("li", { class: "info" }, "E-posta kaydı yok."));
  }

  function markDelivered(o, row) {
    undoable("Teslim alındı olarak işaretlendi", {
      el: row, ic: "check",
      commit: () => api(`/api/orders/${o.id}`, { method: "PATCH", body: { delivered: true } }).then(loadOrders),
    });
  }

  function deleteOrder(o, row) {
    undoable("Sipariş silindi", {
      el: row,
      commit: () => api(`/api/orders/${o.id}`, { method: "PATCH", body: { hidden: true } }).then(loadOrders),
    });
  }

  async function patchOrder(o, body) {
    try { await api(`/api/orders/${o.id}`, { method: "PATCH", body }); loadOrders(); }
    catch (e) { toast(e.message); }
  }

  $("#orders-scan").addEventListener("click", async () => {
    try {
      await api("/api/orders/scan", { method: "POST" });
      state.ordersRunning = true;
      state.ordersAsked = true;
      $("#orders-scan").classList.add("busy");
      loadStatus();
    } catch (e) { toast(e.message); }
  });

  // ------------------------------------------------------------ price tracking
  async function loadTracked() {
    try { state.tracked = await api("/api/tracked"); } catch (_) { return false; }
    renderTracked();
  }

  function renderTrackingMeta(t) {
    const parts = [];
    if (t.running) parts.push("kontrol ediliyor…");
    else if (t.last_run) parts.push(`son kontrol ${ago(t.last_run)}`);
    if (t.next_check) parts.push(`sonraki ${new Date(t.next_check).toLocaleString("tr-TR", { weekday: "short", hour: "2-digit", minute: "2-digit" })}`);
    $("#tracking-meta").textContent = t.items ? parts.join(" · ") : "";
    const btn = $("#track-check");
    btn.hidden = !t.items;
    btn.disabled = t.running;
    btn.textContent = t.running ? "Kontrol ediliyor…" : "Şimdi kontrol et";
  }

  $("#track-check").addEventListener("click", async () => {
    try {
      await api("/api/tracked/check", { method: "POST" });
      state.trackRunning = true;
      loadStatus();
    } catch (e) { toast(e.message); }
  });

  // a small price line: one point per check, the target as a dashed line
  function sparkline(item) {
    const pts = item.history.map((p) => p.price);
    if (pts.length < 2) return h("div", { class: "spark empty small muted" }, pts.length ? "Geçmiş birikiyor…" : "");
    const W = 160, H = 40, pad = 3;
    const vals = item.target_price ? [...pts, item.target_price] : pts;
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const x = (i) => pad + (i * (W - 2 * pad)) / (pts.length - 1);
    const y = (v) => H - pad - ((v - lo) * (H - 2 * pad)) / span;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "spark");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Fiyat geçmişi: ${pts.length} kontrol, en düşük ${fmtPrice(Math.min(...pts))}`);
    const add = (tag, attrs) => { const e = document.createElementNS(ns, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); svg.append(e); };
    if (item.target_price) add("line", { x1: 0, x2: W, y1: y(item.target_price), y2: y(item.target_price), class: "spark-target" });
    add("polyline", { points: pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "), class: "spark-line" });
    add("circle", { cx: x(pts.length - 1), cy: y(pts[pts.length - 1]), r: 2.6, class: "spark-dot" });
    return svg;
  }

  function renderTracked() {
    const box = $("#tracked");
    const hits = state.tracked.filter((x) => x.at_target || x.unseen_alerts).length;
    $("#tab-badge-track").hidden = !hits;
    $("#tab-badge-track").textContent = String(hits);
    if (!state.tracked.length) {
      fill(box, h("p", { class: "empty" }, "Takipte ürün yok. Hızlı aramada bir ürün açıp ", h("b", {}, icon("bell", 14), " Takibe al"),
        "'a dokun: fiyatı her gün kontrol edilir, düşünce haber verilir."));
      return;
    }
    fill(box, ...state.tracked.map(trackedCard));
  }

  function trackedCard(t) {
    const site = t.site_id ? siteById(t.site_id) : null;
    const change = t.change_pct;
    const status = t.at_target ? h("span", { class: "badge free" }, "Hedefe ulaştı")
      : t.unseen_alerts ? h("span", { class: "badge free" }, "Fiyat düştü")
      : t.last_error ? h("span", { class: "badge warn", title: t.last_error }, "Kontrol edilemedi") : null;
    const card = h("article", { class: "track" + (t.at_target || t.unseen_alerts ? " hit" : ""), tabindex: "0", "data-id": t.id,
      title: "Tekliflerini aç",
      onclick: (e) => { if (!e.target.closest("button, a")) openTrackedSearch(t); },
      onkeydown: (e) => { if (e.key === "Enter" && e.target === card) openTrackedSearch(t); } },
      t.image ? h("img", { class: "track-img", src: t.image, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("span", { class: "track-img" }),
      h("div", { class: "track-main" },
        h("div", { class: "track-name", title: t.title }, t.title),
        h("div", { class: "track-meta" },
          t.scope === "mine" ? h("span", { class: "badge" }, "Sitelerim") : null, status,
          t.target_price ? h("span", {}, `Hedef ${fmtPrice(t.target_price)}`) : h("span", {}, "Her düşüşte haber ver"),
          t.low_price ? h("span", {}, `En düşük ${fmtPrice(t.low_price)}`) : null),
        sparkline(t)),
      h("div", { class: "track-price" },
        t.last_price ? h("b", {}, fmtPrice(t.last_price)) : h("b", {}, "—"),
        t.last_store ? h("span", { class: "store-line" }, site ? logo(site) : null, site ? site.name : t.last_store) : null,
        change != null && change !== 0 ? h("span", { class: "chg " + (change < 0 ? "down-good" : "up-bad") },
          `${change > 0 ? "▲" : "▼"} %${Math.abs(change).toLocaleString("tr-TR")} eklenenden beri`) : null,
        h("span", { class: "muted small" }, t.checked_at ? ago(t.checked_at) : "")),
      h("div", { class: "track-actions" },
        t.last_url ? h("a", { class: "btn sm", href: t.last_url, target: "_blank", rel: "noopener noreferrer" }, "En ucuza git ↗") : null,
        h("button", { class: "btn sm ghost", type: "button", onclick: () => openTrackedSearch(t) }, "Teklifler"),
        h("button", { class: "btn sm ghost", type: "button", title: "Sepete ekle", "aria-label": `${t.title} sepete ekle`, onclick: () => addToCart(t.path, t.title, t.image) }, icon("cart", 16)),
        h("button", { class: "btn sm ghost", type: "button", onclick: () => editTracked(t) }, "Hedef"),
        h("button", { class: "icon-btn", type: "button", title: "Takipten çıkar", "aria-label": `${t.title} takipten çıkar`,
          onclick: () => untrack(t) }, icon("x", 15))),
      h("button", { class: "icon-btn more-btn", type: "button", title: "İşlemler", "aria-label": `${t.title} işlemleri`,
        onclick: () => card.classList.toggle("open") }, icon("dots")));
    return card;
  }

  function openTrackedSearch(t) {
    $("#q").value = t.title;
    setScope(t.scope);
    // the product page is the tracked one, whatever Akakçe's search ranks first
    quick(t.title, { product: t.path });
    showPanel("search");
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function editTracked(t) {
    const cur = t.target_price ? String(t.target_price).replace(".", ",") : "";
    const v = prompt("Hedef fiyat (TL). Boş bırakırsan her düşüşte haber verilir.", cur);
    if (v === null) return;
    const num = parseFloat(v.replace(/\./g, "").replace(",", "."));
    const body = v.trim() === "" ? { clear_target: true } : { target_price: num };
    if (v.trim() !== "" && !(num > 0)) { toast("Geçerli bir fiyat girin"); return; }
    try { await api(`/api/tracked/${t.id}`, { method: "PATCH", body }); loadTracked(); }
    catch (e) { toast(e.message); }
  }

  function untrack(t) {
    const card = [...document.querySelectorAll("#tracked .track")].find((c) => c.dataset.id === String(t.id));
    undoable("Takipten çıkarıldı", {
      el: card,
      commit: async () => {
        await api(`/api/tracked/${t.id}`, { method: "DELETE" });
        await loadTracked();
        if (state.result && state.result.tracked_id === t.id) { state.result.tracked_id = null; renderResult(state.result); }
      },
    });
  }

  // ---- "Takibe al": a small box under the 🔔, the target price suggested 10 % under today's cheapest
  function trackPop(r, picked) {
    const best = r.offers.length ? Math.min(...r.offers.map((o) => o.price)) : null;
    const suggest = best ? Math.floor(best * 0.9) : "";
    const scope = r.scope.startsWith("mine") ? "mine" : "all";
    const input = h("input", { type: "text", inputmode: "decimal", value: suggest ? money.format(suggest).replace(/,00$/, "") : "",
      "aria-label": "Hedef fiyat (TL)" });
    const err = h("p", { class: "form-error", hidden: true });
    const send = async (target) => {
      try {
        const item = await api("/api/tracked", { method: "POST", body: {
          path: r.product.path, title: r.product.title || r.query, image: picked && picked.image, scope, target_price: target } });
        state.trackOpen = false;
        r.tracked_id = item.id;
        renderResult(r);
        await loadTracked();
        loadStatus();
        toast(target ? `Takibe alındı — ${fmtPrice(target)} altına inince haber verilecek` : "Takibe alındı — her düşüşte haber verilecek");
      } catch (e) { err.textContent = e.message; err.hidden = false; }
    };
    const form = h("form", { class: "track-pop", role: "dialog", "aria-label": "Fiyat takibi", onsubmit: (e) => {
      e.preventDefault();
      const t = input.value.trim() ? Number(input.value.trim().replace(/\./g, "").replace(",", ".")) : null;
      if (t !== null && !(t > 0)) { err.textContent = "Geçerli bir fiyat girin"; err.hidden = false; return; }
      send(t);
    } },
      h("label", {}, h("span", { class: "small" }, "Hedef fiyat"), h("span", { class: "tp-input" }, input, " TL")),
      best ? h("p", { class: "muted small" }, `Şu an en ucuz ${fmtPrice(best)}${scope === "mine" ? " (sitelerinde)" : ""} · günde 2 kez kontrol, token yok`) : null,
      err,
      h("div", { class: "tp-actions" },
        h("button", { class: "btn sm primary", type: "submit" }, "Takibe al"),
        h("button", { class: "btn sm ghost", type: "button", onclick: () => send(null) }, "Her düşüşte haber ver")));
    setTimeout(() => { input.focus(); input.select(); }, 0);
    return form;
  }
  document.addEventListener("click", (e) => {
    if (state.trackOpen && !e.target.closest(".track-pop, .track-anchor")) { state.trackOpen = false; if (state.result) renderResult(state.result); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.trackOpen) { state.trackOpen = false; if (state.result) renderResult(state.result); }
  });

  // ---- alerts (bell)
  function renderAlertsBadge(n) {
    const c = $("#alerts-count");
    c.hidden = !n;
    c.textContent = n > 9 ? "9+" : String(n);
    $("#alerts-btn").setAttribute("aria-label", n ? `Fiyat alarmları (${n} yeni)` : "Fiyat alarmları");
  }

  async function openAlerts() {
    const pop = $("#alerts-pop"), btn = $("#alerts-btn");
    if (!pop.hidden) { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); return; }
    let data;
    try { data = await api("/api/alerts"); } catch (e) { toast(e.message); return; }
    const list = $("#alerts-list");
    fill(list, ...(data.items.length ? data.items.map((a) => h("li", { class: a.seen ? "" : "new" },
      h(a.url ? "a" : "div", a.url ? { href: a.url, target: "_blank", rel: "noopener noreferrer" } : {},
        h("b", {}, a.kind === "target" ? "Hedef fiyata ulaştı" : "Fiyat düştü"),
        h("span", { class: "a-title" }, a.title),
        h("span", { class: "a-price" },
          a.old_price ? h("s", {}, fmtPrice(a.old_price)) : null, " ", h("b", {}, fmtPrice(a.new_price)), ` · ${a.store || ""}`),
        h("span", { class: "muted small" }, ago(a.created_at)))))
      : [h("li", { class: "empty" }, "Henüz alarm yok. Takipteki bir ürünün fiyatı düşünce burada görünür.")]));
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    if (data.unseen) {
      await api("/api/alerts/seen", { method: "POST" });
      renderAlertsBadge(0);
      loadTracked();
    }
  }
  $("#alerts-btn").addEventListener("click", (e) => { e.stopPropagation(); openAlerts(); });
  document.addEventListener("click", (e) => {
    if (!$("#alerts-pop").hidden && !e.target.closest(".alerts-wrap")) {
      $("#alerts-pop").hidden = true;
      $("#alerts-btn").setAttribute("aria-expanded", "false");
    }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#alerts-pop").hidden) $("#alerts-btn").click(); });

  // ------------------------------------------------------------ shopping list ("Bölerek al")
  async function loadCart() {
    try { state.cart = await api(`/api/cart?scope=${encodeURIComponent(state.scope)}`); } catch (_) { return false; }
    renderCart();
  }

  // every list call answers with the list and its split for the current scope
  async function cartCall(path, opts) {
    const sep = path.includes("?") ? "&" : "?";
    let ok = true;
    try { state.cart = await api(`${path}${sep}scope=${encodeURIComponent(state.scope)}`, opts); renderCart(); }
    catch (e) { toast(e.message); ok = false; }
    if (state.result) {
      const p = state.result.product;
      state.result.cart_id = p ? (state.cart.items.find((i) => i.path === p.path) || {}).id || null : null;
      renderResult(state.result);
    }
    return ok;
  }

  async function addToCart(path, title, image, product = null) {
    if (!await cartCall("/api/cart", { method: "POST", body: { path, title, image, product } })) return;
    const moved = state.cart.moved_from;
    if (moved) {
      // one line per product: picking another store moved it; "Geri al" puts it back where it was
      const now = (state.cart.items.find((i) => i.path === path) || {}).last_store;
      toast(now ? `Artık ${now} mağazasından alınacak` : "Mağaza değiştirildi",
        { label: "Geri al", run: () => cartCall("/api/cart", { method: "POST", body: { path: moved.path, title: moved.title, product } }) }, 6000);
    } else toast("Sepete eklendi");
    setCartOpen(true);   // what was just added is shown; folding it again is the user's call
  }

  function renderCart() {
    const { items, result } = state.cart, box = $("#cart");
    renderCartBadge();
    $("#cart-tools").hidden = !items.length;
    $("#cart-meta").textContent = items.length ? `${items.reduce((n, i) => n + i.qty, 0)} ürün` : "";
    $("#cart-total").textContent = items.length && result && result.total ? fmtPrice(result.total) : "";
    $("#cart-checked").textContent = "";
    // an empty cart is shown open, with its own little scene; there is nothing to fold
    $("#cart-card").classList.toggle("is-empty", !items.length);
    $("#cart-toggle").disabled = !items.length;
    if (!items.length) {
      fill(box, h("div", { class: "no-active" }, emptyScene(CART_SVG),
        h("p", { class: "empty" }, "Sepetin boş."),
        h("p", { class: "muted small hint" }, "Bir ürün arayıp almak istediğin mağazanın ", h("b", {}, icon("cart", 14)),
          " simgesine dokun: mağaza mağaza siparişlerin ve toplamı burada görünür.")));
      return;
    }
    fill(box, ...cartGroups(items, result));
  }

  // shipping per store: free, the fee the user entered, or unknown — click to enter or change it
  function shippingLabel(o) {
    if (o.free_shipping) return h("span", { class: "ok small" }, "Ücretsiz kargo");
    const cfg = (state.cart.shipping || {})[o.store];
    const text = o.shipping == null ? "+ kargo ? (ücreti gir)"
      : o.shipping === 0 ? `kargo ücretsiz (${fmtPrice(cfg.free_over)} üstü)` : `+ ${fmtPrice(o.shipping)} kargo`;
    return h("button", { class: "ship-btn small" + (o.shipping == null ? " unknown" : ""), type: "button",
      "aria-expanded": String(state.shipEdit === o.store), title: "Bu mağazanın kargo ücreti",
      onclick: () => { state.shipEdit = state.shipEdit === o.store ? null : o.store; renderCart(); } }, text);
  }

  function shippingForm(store) {
    const cfg = (state.cart.shipping || {})[store] || {};
    const num = (v) => { const t = String(v).trim().replace(/\./g, "").replace(",", "."); return t ? Number(t) : null; };
    const tr = (v) => (v == null ? "" : money.format(v).replace(/,00$/, ""));     // 49,90 / 500
    const fee = h("input", { type: "text", inputmode: "decimal", placeholder: "49,90", value: tr(cfg.fee), "aria-label": "Kargo ücreti (TL)" });
    const over = h("input", { type: "text", inputmode: "decimal", placeholder: "500", value: tr(cfg.free_over), "aria-label": "Bu tutardan sonra ücretsiz (TL)" });
    const save = async (body) => {
      try {
        state.cart = await api(`/api/shipping?scope=${encodeURIComponent(state.scope)}`, { method: "PUT", body: { store, ...body } });
        state.shipEdit = null;
        renderCart();
      } catch (e) { toast(e.message); }
    };
    const form = h("form", { class: "ship-form", onsubmit: (e) => {
      e.preventDefault();
      const f = num(fee.value), o = num(over.value);
      if ((f != null && Number.isNaN(f)) || (o != null && Number.isNaN(o))) { toast("Geçerli bir tutar girin"); return; }
      save({ fee: f, free_over: o });
    } },
      h("label", {}, "Kargo ", fee, " TL"), h("label", {}, over, " TL üstü ücretsiz"),
      h("button", { class: "btn sm primary", type: "submit" }, "Kaydet"),
      cfg.fee != null || cfg.free_over != null
        ? h("button", { class: "btn sm ghost", type: "button", onclick: () => save({ fee: null, free_over: null }) }, "Unut") : null);
    setTimeout(() => fee.focus(), 0);
    return form;
  }

  // one row per product: picture, title (to the seller), price, quantity, remove
  function cartRow(it, pick, note) {
    const price = pick ? (pick.qty > 1 ? `${pick.qty} × ${fmtPrice(pick.price)}` : fmtPrice(pick.price)) : null;
    return h("li", { class: "cart-row" },
      productImg(it.image, "cr-img") || h("span", { class: "cr-img ph" }),
      h("div", { class: "cr-text" },
        pick && pick.url ? h("a", { class: "cr-title", href: pick.url, target: "_blank", rel: "noopener noreferrer", title: `${it.title} — satıcıya git` },
          it.title, " ↗") : h("span", { class: "cr-title", title: it.title }, it.title),
        note ? h("span", { class: "cr-note" }, note) : null),
      price ? h("span", { class: "cr-price" }, price) : h("span"),
      h("span", { class: "cr-controls" },
        h("span", { class: "qty", role: "group", "aria-label": `${it.title} adedi` },
          h("button", { type: "button", "aria-label": "Bir azalt", disabled: it.qty <= 1,
            onclick: () => cartCall(`/api/cart/${it.id}`, { method: "PATCH", body: { qty: it.qty - 1 } }) }, "−"),
          h("b", {}, String(it.qty)),
          h("button", { type: "button", "aria-label": "Bir artır",
            onclick: () => cartCall(`/api/cart/${it.id}`, { method: "PATCH", body: { qty: it.qty + 1 } }) }, "+")),
        h("button", { class: "icon-btn", type: "button", title: "Sepetten çıkar", "aria-label": `${it.title} sepetten çıkar`,
          onclick: (e) => {
            const row = e.currentTarget.closest(".cart-row");
            undoable("Sepetten çıkarıldı", {
              el: row, ms: CART_UNDO_MS,
              commit: () => cartCall(`/api/cart/${it.id}`, { method: "DELETE" }),
            });
          } }, icon("x", 15))));
  }

  // "Bölerek al": every product once, under the store where it is cheapest; the total is on the header line
  function cartGroups(items, r) {
    const byId = new Map(items.map((it) => [it.id, it]));
    const out = [];
    if (r) {
      const tools = [r.scope !== "all" ? scopeLabel(r.scope) : null, `${r.orders.length} ayrı sipariş`,
        r.shipping_unknown ? "kargo hariç" : null].filter(Boolean).join(" · ");
      $("#cart-checked").textContent = [tools, r.checked_at ? `fiyatlar ${ago(r.checked_at)}` : null].filter(Boolean).join(" · ");
      for (const o of r.orders) {
        const site = o.site_id ? siteById(o.site_id) : null;
        out.push(h("section", { class: "cart-group" },
          h("div", { class: "cg-head" }, logo(site, o.store), h("b", {}, site ? site.name : o.store),
            shippingLabel(o), h("span", { class: "cg-total" }, fmtPrice(o.grand ?? o.total))),
          state.shipEdit === o.store ? shippingForm(o.store) : null,
          h("ol", { class: "cart-rows" }, o.items.map((p) => byId.has(p.id) ? cartRow(byId.get(p.id), p) : null))));
      }
      if (r.missing.length) {
        out.push(h("section", { class: "cart-group missing-group" },
          h("div", { class: "cg-head" }, h("b", {}, "Fiyatı bulunamayan")),
          h("ol", { class: "cart-rows" }, r.missing.map((m) => byId.has(m.id) ? cartRow(byId.get(m.id), null, m.reason) : null))));
      }
      out.push(singleStore(r));
    } else {
      out.push(h("ol", { class: "cart-rows" }, items.map((it) => cartRow(it, null, "Fiyat henüz okunmadı"))));
    }
    return out;
  }

  // rail cards that fold to their header line; each remembers whether it was left open
  function collapsible(card, toggle, key, defaultOpen) {
    const set = (open, remember = true) => {
      card.classList.toggle("expanded", open);
      toggle.setAttribute("aria-expanded", String(open));
      if (remember) try { localStorage.setItem(key, open ? "1" : "0"); } catch (_) { /* private mode */ }
    };
    toggle.addEventListener("click", () => set(!card.classList.contains("expanded")));
    let saved = null;
    try { saved = localStorage.getItem(key); } catch (_) { /* private mode */ }
    set(saved === null ? defaultOpen : saved === "1", false);
    return set;
  }
  // the cart starts as one line (count and total): open it would push the orders out of sight
  const setCartOpen = collapsible($("#cart-card"), $("#cart-toggle"), "commerce_cart_open", false);
  const setOrdersOpen = collapsible($("#orders-card"), $("#orders-toggle"), "commerce_orders_open", true);

  function singleStore(r) {
    const s = r.single;
    if (!s || r.orders.length < 2) return null;                  // already a single order
    if (s.full.length) {
      const top = s.full[0];
      return h("details", { class: "single", open: state.singleOpen || null,
        ontoggle: (e) => { state.singleOpen = e.target.open; } },
        h("summary", { class: "single-head" }, "Tek siparişte: ", h("b", {}, top.store), ` ${fmtPrice(top.total)}`,
          h("span", { class: top.extra > 0 ? "s-more" : "s-same" }, top.extra > 0 ? ` (+${fmtPrice(top.extra)})` : " (aynı)")),
        s.full.map((o) => {
          const site = o.site_id ? siteById(o.site_id) : null;
          return h("div", { class: "single-row" }, logo(site, o.store), h("span", { class: "s-name" }, site ? site.name : o.store),
            o.free_shipping || o.shipping != null ? null : h("span", { class: "warn small" }, "+ kargo"),
            h("span", { class: "s-total" }, fmtPrice(o.total)),
            h("span", { class: "s-extra" + (o.extra > 0 ? "" : " same") }, o.extra > 0 ? `+${fmtPrice(o.extra)}` : "aynı"));
        }));
    }
    const p = s.best_partial;
    if (!p) return null;
    return h("details", { class: "single", open: state.singleOpen || null,
      ontoggle: (e) => { state.singleOpen = e.target.open; } },
      h("summary", { class: "single-head" }, "Tek siparişte: hiçbir mağazada hepsi yok"),
      h("p", { class: "single-none" }, `Hiçbir mağazada listenin tamamı yok. En çoğu ${p.store}'da: ${p.count}/${p.of} ürün, `,
        h("b", {}, fmtPrice(p.total)), ` (eksik: ${p.missing.join(", ")}).`));
  }

  $("#cart-compare").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "Hesaplanıyor…";
    state.busy = "cart";
    renderHealth();
    try { await cartCall("/api/cart/compare", { method: "POST", body: { scope: state.scope } }); }
    finally {
      state.busy = false;
      btn.disabled = false;
      btn.textContent = "Fiyatları güncelle";
      renderHealth();
    }
  });
  $("#cart-clear").addEventListener("click", () => {
    undoable("Sepet boşaltıldı", {
      el: $("#cart"), ms: CART_UNDO_MS,
      commit: () => cartCall("/api/cart", { method: "DELETE" }),
    });
  });

  // ------------------------------------------------------------ layout: dock, recent, drawer, views
  // my stores as a row of logos under the search; managing them happens in the drawer
  function renderDock() {
    const groups = state.groups;
    const chips = groups.length ? [{ key: "all", name: "Tümü" }, ...groups.map((g) => ({ key: String(g.id), name: g.name })),
      ...(state.sites.some((s) => s.group_id == null) ? [{ key: "", name: "Diğer" }] : [])] : [];
    const sel = $("#dock-group");
    sel.hidden = !chips.length;
    fill(sel, ...chips.map((c) => h("option", { value: c.key, selected: state.groupFilter === c.key }, c.name)));
    // the strip keeps one order across groups (the drawer shows the same order group by group)
    const byPos = [...state.sites].sort((a, b) => (a.position ?? 1e9) - (b.position ?? 1e9) || a.id - b.id);
    const list = state.groupFilter === "all" ? byPos : byPos.filter((s) => groupKey(s.group_id) === state.groupFilter);
    fill($("#dock"), ...[
      // a scrolling row clips CSS labels: the browser tooltip shows the name
      ...list.map((s) => h("a", { href: s.url, target: "_blank", rel: "noopener", title: s.name, "aria-label": s.name,
        draggable: "false", "data-id": s.id, "data-group": groupKey(s.group_id) }, logo(s))),
      list.length ? null : h("span", { class: "empty-dock" }, "Bu grupta site yok."),
      // "+" opens the stores editor (adding a site, groups and order all live there)
      h("button", { class: "dock-add", type: "button", title: "Sitelerimi düzenle", "aria-label": "Sitelerimi düzenle",
        onclick: () => openDrawer("sites") }, icon("plus", 20)),
    ].filter(Boolean));   // replaceChildren would print a null
  }

  function renderRecent(items) {
    const box = $("#recent");
    box.hidden = !items.length;
    fill(box, h("span", {}, "Son:"),
      ...items.slice(0, 4).map((it) => h("button", { class: "chip", type: "button", title: it.title || it.query,
        onclick: () => rerun(it) }, it.query)),
      h("button", { class: "more", type: "button", onclick: () => openDrawer("history") }, "Geçmiş →"));
  }

  // the item count on the phone's "Sepet" tab (the rail card shows the rest)
  function renderCartBadge() {
    const n = state.cart.items.reduce((k, i) => k + i.qty, 0);
    const badge = $("#tab-badge-cart");
    badge.hidden = !n;
    badge.textContent = String(n);
  }

  // drawer: managing stores and the full history (full screen on a phone, above the tab bar)
  let drawerFrom = null;
  function openDrawer(which) {
    drawerFrom = document.activeElement;
    $("#sites-panel").hidden = which !== "sites";
    $("#history-panel").hidden = which !== "history";
    $("#drawer").hidden = $("#drawer-backdrop").hidden = false;
    $("#drawer").dataset.panel = which;
    if (which === "sites") { state.editing = false; setEditing(true); }
    $("#drawer").querySelector(".drawer-close")?.focus();
  }
  function closeDrawer() {
    if ($("#drawer").hidden) return;
    $("#drawer").hidden = $("#drawer-backdrop").hidden = true;
    setEditing(false);
    if (document.body.dataset.view === "sites") setView("search");
    drawerFrom?.focus?.();
  }
  document.querySelectorAll(".drawer-close").forEach((b) => b.addEventListener("click", closeDrawer));
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#drawer").hidden && !document.querySelector("dialog[open]")) closeDrawer();
  });
  $("#dock-group").addEventListener("change", (e) => setGroupFilter(e.target.value));

  // reorder the strip by dragging a logo left or right, anywhere in the row (its group stays; moving a
  // store to another group is in "Düzenle").
  // Mouse: drag after a few pixels. Touch: hold a moment first, so a swipe still scrolls the row.
  (() => {
    const dock = $("#dock");
    let d = null, eatClick = false;
    const logos = () => [...dock.querySelectorAll("a[data-id]")];
    function begin() {
      d.on = true;
      d.el.classList.add("dragging");
      dock.classList.add("sorting");
      try { d.el.setPointerCapture(d.pid); } catch (_) { /* pointer already gone */ }
    }
    function follow(x) {
      d.el.style.transform = `translateX(${x - d.x}px)`;
      const others = logos().filter((a) => a !== d.el);
      const before = others.find((a) => { const r = a.getBoundingClientRect(); return x < r.left + r.width / 2; });
      const anchor = before || (others.length ? others[others.length - 1].nextSibling : null);
      if (anchor === d.el || anchor === d.el.nextSibling) return;
      const was = d.el.getBoundingClientRect().left;
      dock.insertBefore(d.el, anchor);
      d.x += d.el.getBoundingClientRect().left - was;          // stay under the pointer in the new slot
      d.el.style.transform = `translateX(${x - d.x}px)`;
    }
    async function finish() {
      const moved = d.on;
      d.el.classList.remove("dragging");
      d.el.style.transform = "";
      dock.classList.remove("sorting");
      clearTimeout(d.timer);
      const el = d.el;
      d = null;
      if (!moved) return;
      eatClick = true;                                          // the drop is not a click on the store
      const ids = logos().map((a) => Number(a.dataset.id));
      try { await api("/api/sites/order", { method: "PUT", body: { ids } }); }
      catch (e) { toast(e.message); }
      loadSites();
    }
    dock.addEventListener("pointerdown", (e) => {
      const a = e.target.closest("a[data-id]");
      if (!a || e.button > 0 || d) return;
      d = { el: a, pid: e.pointerId, x: e.clientX, y: e.clientY, on: false, touch: e.pointerType !== "mouse", timer: null };
      if (d.touch) d.timer = setTimeout(() => { if (d && !d.on) begin(); }, 350);
    });
    // moves and the release are followed on the whole page: moving the logo in the row drops the
    // pointer capture, and the pointer may leave the strip while dragging
    addEventListener("pointermove", (e) => {
      if (!d || e.pointerId !== d.pid) return;
      if (!d.on) {
        const far = Math.abs(e.clientX - d.x) > 6 || Math.abs(e.clientY - d.y) > 6;
        if (d.touch) { if (far) { clearTimeout(d.timer); d = null; } return; }   // a swipe: let the row scroll
        if (!far) return;
        begin();
      }
      e.preventDefault();
      follow(e.clientX);
    });
    addEventListener("pointerup", (e) => {
      if (!d || e.pointerId !== d.pid) return;
      // a quick flick may end before any move reached the drop point: the release decides
      if (!d.on && !d.touch && Math.abs(e.clientX - d.x) > 6) begin();
      if (d.on) follow(e.clientX);
      finish();
    });
    addEventListener("pointercancel", (e) => { if (d && e.pointerId === d.pid) finish(); });
    dock.addEventListener("click", (e) => { if (eatClick) { e.preventDefault(); eatClick = false; } }, true);
    // the browser's own drag of the logo image (or link) would cancel ours mid-way (pointercancel)
    dock.addEventListener("dragstart", (e) => e.preventDefault());
  })();

  // views (bottom tab bar, below 1000 px): search · track · orders · cart · sites
  const NARROW = matchMedia("(max-width: 999px)");
  function setView(view) {
    document.body.dataset.view = view;
    document.querySelectorAll("#tabbar [data-view]").forEach((b) => {
      if (b.dataset.view === view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    if (view !== "sites") try { localStorage.setItem("commerce_view", view); } catch (_) { /* private mode */ }
  }
  document.querySelectorAll("#tabbar [data-view]").forEach((b) => b.addEventListener("click", () => {
    const view = b.dataset.view;
    if (view === "sites") { setView("sites"); openDrawer("sites"); return; }
    closeDrawer();
    setView(view);
    scrollTo({ top: 0 });
  }));
  // bring a panel into view: on a phone switch the tab, on a wide screen it is already beside the results
  function showPanel(view) {
    if (NARROW.matches) { closeDrawer(); setView(view); scrollTo({ top: 0 }); return; }
    if (view === "cart") setCartOpen(true);
    if (view === "orders") setOrdersOpen(true);
    const el = view === "cart" ? $("#cart-card") : view === "track" ? $("#tracking-card") : view === "orders" ? $("#orders-card") : null;
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "nearest" }); el.animate([{ outline: "2px solid var(--accent)" }, { outline: "2px solid transparent" }], { duration: 900 }); }
  }

  window.commerceGuide = { setView, showPanel, openDrawer };      // guide.js's "Göster" uses these

  // ------------------------------------------------------------ history
  async function loadHistory() {
    let items = [];
    try { items = await api("/api/history"); } catch (_) { return false; }
    renderRecent(items);
    const list = $("#history");
    $("#clear-history").hidden = !items.length;
    if (!items.length) {
      fill(list, h("li", { class: "empty muted" }, "Henüz arama yok."));
      return;
    }
    fill(list, ...items.map((it) => h("li", {},
      h("button", { class: "h-open", type: "button", title: it.kind === "deep" ? "Kayıttan aç (token harcamaz)" : "Yeniden ara (token yok)", onclick: () => rerun(it) },
        h("span", { class: "h-q" }, it.title && it.title.toLocaleLowerCase("tr-TR") !== it.query.toLocaleLowerCase("tr-TR") ? `${it.query} — ${it.title}` : it.query),
        h("span", { class: "h-meta" },
          it.kind === "deep" ? h("span", { class: "badge ai" }, `Derin · ${fmtTokens(it.tokens)}`) : h("span", { class: "badge free" }, "Hızlı"),
          it.scope !== "all" ? h("span", { class: "badge" }, scopeLabel(it.scope)) : null,
          it.min_price != null ? h("span", { class: "h-price" }, `${fmtPrice(it.min_price)}'den`) : null,
          `${it.offers} teklif · ${ago(it.created_at)}`)),
      h("button", { class: "icon-btn", type: "button", title: "Sil", "aria-label": `${it.query} aramasını sil`,
        onclick: async () => { await api(`/api/history/${it.id}`, { method: "DELETE" }); loadHistory(); } }, icon("x", 15)))));
  }

  // a past search runs again (token-free quick search, same stores); a deep one opens as it was
  // saved, since running it again would spend tokens
  function rerun(it) {
    if (it.kind === "deep") { openHistory(it.id); return; }
    setScope(it.scope);
    $("#q").value = it.query;
    closeDrawer();
    showPanel("search");
    quick(it.query);
  }

  async function openHistory(id) {
    try {
      const r = await api(`/api/history/${id}`);
      state.result = r;
      setScope(r.scope);
      $("#q").value = r.query;
      renderResult(r);
      closeDrawer();
      showPanel("search");
    } catch (e) { toast(e.message); }
  }

  $("#clear-history").addEventListener("click", () => {
    const list = $("#history");
    undoable("Arama geçmişi temizlendi", {
      el: list,
      commit: async () => { await api("/api/history", { method: "DELETE" }); list.hidden = false; loadHistory(); },
    });
  });

  // ------------------------------------------------------------ start
  let saved = "all";
  try { saved = localStorage.getItem("commerce_scope") || "all"; } catch (_) { /* private mode */ }
  setScope(saved.startsWith("mine") ? saved : "all");   // a group scope is checked again once groups load
  try { state.groupFilter = localStorage.getItem("commerce_group_filter") || "all"; } catch (_) { /* private mode */ }
  let savedView = "search";
  try { savedView = localStorage.getItem("commerce_view") || "search"; } catch (_) { /* private mode */ }
  setView(["search", "track", "orders", "cart"].includes(savedView) ? savedView : "search");
  try { (localStorage.getItem("commerce_filters") || "").split(",").filter(Boolean).forEach((k) => state.filters.add(k)); }
  catch (_) { /* private mode */ }
  // boot screen: every log line waits for the real thing it names
  const { track, mark, finish: bootDone } = window.commerceBoot;
  const firstStatus = new Promise((resolve, reject) => { state.onStatus = resolve; state.onStatusFail = reject; });
  // Akakçe is probed in the background after start; its line closes when the first answer is in
  const akakceKnown = new Promise((resolve) => { state.onAkakce = resolve; });
  Promise.allSettled([
    track("tracked", loadTracked()),
    loadOrders(),
    track("sites", loadSites().catch((e) => { toast(e.message); throw e; })),
    track("history", loadHistory()),
    track("server", firstStatus).then((s) => {
      mark("gemini", s.ai_ready);
      return track("akakce", akakceKnown);
    }, () => { mark("akakce", false); mark("gemini", false); }),
  ]).then(bootDone);
  loadStatus();
  loadCart();
  // logos of a fresh install arrive in the background during the first seconds
  setTimeout(() => { if (state.sites.some((s) => !s.logo)) loadSites().catch(() => {}); }, 6000);
})();
