/* Remo app shell: routing, voice widget, pages, toasts. Vanilla JS. */
(() => {
  const $ = (id) => document.getElementById(id);
  const API = window.RemoAPI;

  const store = {
    lang: localStorage.getItem("remo-lang") || "hi-IN",
    autoplay: localStorage.getItem("remo-autoplay") !== "off",
    pending: null,
    cache: null,
    briefSpoken: null,
  };
  const LANG_NAME = { "hi-IN": "Hinglish", "mr-IN": "Marathi" };
  const player = new Audio();
  let speaking = false;

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmtTime(ts) {
    return new Date(ts * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  }
  function toast(text, err) {
    const box = $("toasts");
    const div = document.createElement("div");
    div.className = "toast" + (err ? " err" : "");
    div.textContent = text;
    box.appendChild(div);
    setTimeout(() => div.remove(), 4200);
    while (box.children.length > 4) box.firstChild.remove();
  }
  function setSide(state, label) {
    $("side-dot").className = `dot ${state}`;
    $("side-status").textContent = label;
  }
  function play(url, done) {
    if (!url || !store.autoplay) { done && done(); return; }
    speaking = true;
    player.src = url;
    const end = () => { speaking = false; done && done(); };
    player.onended = end;
    player.onerror = end;
    player.play().catch(end);
  }

  /* ---------- router ---------- */
  const PAGES = ["home", "ask", "memories", "work", "reminders", "watchlist", "briefing", "voice", "settings"];
  function route() {
    const name = (location.hash.replace("#/", "") || "home").split("?")[0];
    const page = PAGES.includes(name) ? name : "home";
    PAGES.forEach((p) => { $(`page-${p}`).hidden = p !== page; });
    document.querySelectorAll(".side-nav a").forEach((a) => {
      a.classList.toggle("active", a.dataset.page === page);
    });
    document.querySelector(".shell").classList.remove("open");
    $("scrim").hidden = true;
    if (page === "briefing") renderBriefing();
  }
  window.addEventListener("hashchange", route);

  /* ---------- threads ---------- */
  function pendingChips(data, box) {
    if (!data.pending || !["undo", "forget", "remind"].includes(data.pending.action)) return;
    const row = document.createElement("div");
    row.className = "row";
    ["Haan", "Nahi"].forEach((label) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = label;
      b.onclick = () => submitText(label, box);
      row.appendChild(b);
    });
    box.appendChild(row);
  }

  function addTurn(box, who, text, data) {
    const div = document.createElement("div");
    div.className = `turn${who === "You" ? " you" : ""}`;
    let html = `<div class="who">${who}</div><p>${esc(text)}</p>`;
    if (data && data.links && data.links.length) {
      html += `<div class="links">${data.links.map((l) =>
        `<a href="${esc(l)}" target="_blank" rel="noopener">source</a>`).join("")}</div>`;
    }
    div.innerHTML = html;
    if (data && data.audio_url) {
      const row = document.createElement("div");
      row.className = "row";
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = "replay voice";
      b.onclick = () => play(data.audio_url);
      row.appendChild(b);
      div.appendChild(row);
    }
    if (data) pendingChips(data, div);
    box.prepend(div);
    while (box.children.length > 30) box.lastChild.remove();
  }

  async function submitText(text, box, opts = {}) {
    const value = (text || "").trim();
    if (!value) return;
    setSide("thinking", "Thinking");
    try {
      const data = await API.turnText(value, store.lang, store.pending);
      store.pending = data.pending || null;
      showPendingChip();
      addTurn(box, "You", value, null);
      addTurn(box, "Remo", data.text, data);
      if (!opts.quiet) play(data.audio_url, refresh);
      else refresh();
    } catch (err) {
      toast(`Send failed: ${err.message}`, true);
    } finally {
      setSide("ready", "Ready");
    }
  }

  function showPendingChip() {
    const el = $("v-pending");
    if (!store.pending || !store.pending.action) { el.hidden = true; return; }
    const labels = { undo: "waiting: forget last? (haan / nahi)", forget: "waiting: forget this? (haan / nahi)",
      remind: "waiting: arm reminder? (haan / nahi)", remind_ask: "waiting: what for?",
      quiz: "quiz live: answer or say bas" };
    el.textContent = labels[store.pending.action] || "waiting";
    el.hidden = false;
  }

  /* ---------- voice widget (home + ask share the engine) ---------- */
  function makeVoice({ micBtn, stateEl, timerEl, heardEl, waveEl, box, autoPlay = true }) {
    const session = window.RemoVoice.createSession({
      onLevel: (data) => drawWave(waveEl, data),
      onDone: async (wav) => {
        stopTimer();
        setState("processing", "Thinking");
        setSide("thinking", "Thinking");
        try {
          const data = await API.turnAudio(wav, store.lang, store.pending);
          store.pending = data.pending || null;
          showPendingChip();
          if (data.transcript) {
            heardEl.textContent = `Heard: ${data.transcript}`;
            heardEl.hidden = false;
            addTurn(box, "You", data.transcript, null);
          }
          addTurn(box, "Remo", data.text, data);
          setState("responding", "Here is what I found");
          setSide("speaking", "Speaking");
          const end = () => { setState("idle", "Tap to talk to Remo"); setSide("ready", "Ready"); refresh(); };
          if (autoPlay && store.autoplay) play(data.audio_url, end);
          else { end(); if (data.audio_url && !store.autoplay) toast("Reply ready (autoplay is off)"); }
        } catch (err) {
          setState("error", `Could not reach Remo (${err.message})`);
          setSide("bad", "Error");
          toast(`Voice turn failed: ${err.message}`, true);
        }
      },
      onError: (err) => {
        stopTimer();
        setState("error", `Recording failed (${err.message})`);
        setSide("bad", "Error");
      },
    });

    let timer = 0, timerInt = 0;
    function startTimer() {
      timer = 0;
      timerEl.hidden = false;
      timerInt = setInterval(() => {
        timer += 1;
        timerEl.textContent = `${Math.floor(timer / 60)}:${String(timer % 60).padStart(2, "0")}`;
      }, 1000);
    }
    function stopTimer() { clearInterval(timerInt); timerEl.hidden = true; }
    function setState(mode, label) {
      stateEl.textContent = label;
      stateEl.classList.toggle("err", mode === "error");
      micBtn.classList.toggle("live", mode === "listening");
    }
    async function toggle() {
      if (session.isLive()) { session.stop(); return; }
      heardEl.hidden = true;
      try {
        await session.start();
        startTimer();
        setState("listening", "I am listening");
        setSide("listening", "Listening");
      } catch (err) {
        setState("error", `Microphone blocked (${err.message})`);
        toast("Allow microphone access and retry", true);
      }
    }
    micBtn.onclick = toggle;
    return { toggle };
  }

  const ACCENT = "#4cc9b0", TRACK = "#222b2f";
  function drawWave(canvas, data) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = ACCENT;
    const n = 56, bw = W / n;
    for (let i = 0; i < n; i++) {
      const v = data[Math.floor((i / n) * data.length * 0.7)] / 255;
      const h = Math.max(3, v * (H - 10));
      ctx.fillRect(i * bw + bw * 0.25, (H - h) / 2, bw * 0.5, h);
    }
  }
  function idleWave(canvas) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = TRACK;
    const n = 56, bw = W / n;
    for (let i = 0; i < n; i++) {
      const h = 3 + 2 * Math.sin(i * 0.7);
      ctx.fillRect(i * bw + bw * 0.25, (H - h) / 2, bw * 0.5, h);
    }
  }

  /* ---------- data + pages ---------- */
  function skeleton(list, rows = 3) {
    list.innerHTML = "";
    for (let i = 0; i < rows; i++) {
      const li = document.createElement("li");
      li.className = "skel";
      list.appendChild(li);
    }
  }

  async function refresh() {
    try {
      const s = await API.state();
      store.cache = s;
      renderAll(s);
      $("conn").innerHTML = `<span class="dot ready"></span><span>Connected</span>`;
    } catch {
      $("conn").innerHTML = `<span class="dot bad"></span><span>Server away</span>`;
    }
  }

  function pendingCount(s) {
    return s.work.reduce((a, w) => a + w.pending.length, 0);
  }

  function badge(id, n) {
    const el = $(id);
    if (n > 0) { el.textContent = n > 99 ? "99+" : String(n); el.hidden = false; }
    else el.hidden = true;
  }

  function renderAll(s) {
    $("stat-notes").textContent = s.notes.length;
    $("stat-pending").textContent = pendingCount(s);
    $("stat-rem").textContent = s.reminders.length;
    $("stat-watch").textContent = s.watched.length;
    badge("badge-notes", s.notes.length);
    badge("badge-work", pendingCount(s));
    badge("badge-rem", s.reminders.length);
    badge("badge-watch", s.changes.filter((c) => !c.briefed).length);

    const act = $("activity");
    act.innerHTML = "";
    const items = [
      ...s.notes.slice(0, 4).map((n) => ({ icon: "i-archive", text: n.text, meta: `saved ${fmtTime(n.created_at)}` })),
      ...s.reminders.slice(0, 3).map((r) => ({ icon: "i-bell", text: r.text, meta: `fires ${r.when}` })),
      ...s.changes.slice(0, 3).map((c) => ({ icon: "i-eye", text: c.summary, meta: "watcher update" })),
    ].slice(0, 8);
    if (!items.length) act.innerHTML = `<li class="empty">Quiet so far. Speak to Remo to begin.</li>`;
    items.forEach((it) => {
      const li = document.createElement("li");
      li.innerHTML = `${esc(it.text)}<span class="meta">${esc(it.meta)}</span>`;
      act.appendChild(li);
    });

    renderMemories(s);
    renderWork(s);
    renderReminders(s);
    renderWatch(s);
    renderContext(s);
  }

  function renderMemories(s) {
    const q = ($("mem-search").value || "").toLowerCase();
    const list = $("mem-list");
    const hits = s.notes.filter((n) => !q || n.text.toLowerCase().includes(q));
    list.innerHTML = hits.length ? "" : `<li class="empty">${s.notes.length ? "No matches." : "No memories yet. Say: yaad rakhna ..."}</li>`;
    hits.slice(0, 60).forEach((n) => {
      const li = document.createElement("li");
      li.innerHTML = `${esc(n.text)}<span class="meta">${esc(fmtTime(n.created_at))} · ${esc(n.source || "voice")}</span>`;
      list.appendChild(li);
    });
  }

  function renderWork(s) {
    const box = $("work-list");
    box.innerHTML = s.work.length ? "" : `<div class="panel"><p class="empty">No work tracked. Speak a progress update to start.</p></div>`;
    s.work.forEach((w) => {
      const label = [w.org, w.issue_ref ? `issue ${w.issue_ref}` : ""].filter(Boolean).join(" ") || "general";
      const div = document.createElement("div");
      div.className = "panel";
      const pend = w.pending.map((p) => `<li class="pend-item">${esc(p)}</li>`).join("") || `<li class="empty">Nothing pending.</li>`;
      const done = w.done.map((d) => `<li class="done-item">${esc(d)}</li>`).join("") || `<li class="empty">Nothing done yet.</li>`;
      div.innerHTML = `<h3>${esc(label)} <span class="muted small">${esc(w.persona)}</span></h3>
        <ul class="rows">${pend}</ul><ul class="rows" style="margin-top:.5rem">${done}</ul>`;
      box.appendChild(div);
    });
  }

  function renderReminders(s) {
    const up = $("rem-list"), done = $("rem-done");
    up.innerHTML = s.reminders.length ? "" : `<li class="empty">None armed.</li>`;
    s.reminders.forEach((r) => {
      const li = document.createElement("li");
      li.innerHTML = `${esc(r.text)}<span class="meta">${esc(r.when)}</span>`;
      up.appendChild(li);
    });
    done.innerHTML = s.reminders_fired.length ? "" : `<li class="empty">None completed yet.</li>`;
    s.reminders_fired.slice(0, 20).forEach((r) => {
      const li = document.createElement("li");
      li.innerHTML = `${esc(r.text)}<span class="meta">fired ${esc(r.when)}</span>`;
      done.appendChild(li);
    });
  }

  function renderWatch(s) {
    const box = $("watch-list");
    box.innerHTML = s.watched.length ? "" : `<div class="panel"><p class="empty">Nothing watched. Paste a GitHub link above, or say: watch karo ...</p></div>`;
    s.watched.forEach((w) => {
      const fresh = s.changes.filter((c) => c.watch_url === w.url).slice(0, 4);
      const div = document.createElement("div");
      div.className = "panel";
      div.innerHTML = `<h3><a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(shortUrl(w.url))}</a>
        ${fresh.some((c) => !c.briefed) ? `<span class="pill-new">new</span>` : ""}</h3>
        <p class="muted small">Last checked: ${w.checked_at ? esc(fmtTime(w.checked_at)) : "never"}</p>
        <ul class="rows">${fresh.length ? fresh.map((c) =>
          `<li>${esc(c.summary)}<span class="meta"><a href="${esc(c.link)}" target="_blank" rel="noopener">open</a></span></li>`
        ).join("") : `<li class="empty">No changes recorded yet.</li>`}</ul>`;
      box.appendChild(div);
    });
  }

  function shortUrl(url) {
    try {
      const u = new URL(url);
      return u.pathname.replace(/^\//, "") || u.host;
    } catch { return url; }
  }

  function renderContext(s) {
    const firstPending = s.work.flatMap((w) => w.pending.map((p) => ({ p, w })))[0];
    $("ctx-next").textContent = firstPending
      ? `${firstPending.p} (${[firstPending.w.org, firstPending.w.issue_ref ? `issue ${firstPending.w.issue_ref}` : ""].filter(Boolean).join(" ") || "general"})`
      : "All clear. Nothing pending.";
    const rem = $("ctx-rem");
    rem.innerHTML = s.reminders.length ? "" : `<li class="muted">No reminders today.</li>`;
    s.reminders.slice(0, 5).forEach((r) => {
      const li = document.createElement("li");
      li.innerHTML = `${esc(r.text)}<span class="meta">${esc(r.when)}</span>`;
      rem.appendChild(li);
    });
    const ch = $("ctx-changes");
    const fresh = s.changes.slice(0, 5);
    ch.innerHTML = fresh.length ? "" : `<li class="muted">No changes yet.</li>`;
    fresh.forEach((c) => {
      const li = document.createElement("li");
      li.innerHTML = `${esc(c.summary)}<span class="meta"><a href="${esc(c.link)}" target="_blank" rel="noopener">open</a></span>`;
      ch.appendChild(li);
    });
  }

  function renderBriefing() {
    const s = store.cache;
    const box = $("brief-body");
    if (!s) { box.innerHTML = `<div class="panel"><p class="empty">Loading your briefing.</p></div>`; return; }
    const pend = s.work.flatMap((w) => w.pending.map((p) => ({ p, w })));
    const fresh = s.changes.filter((c) => !c.briefed);
    const next = pend[0];
    box.innerHTML = "";
    const sections = [
      ["Pending work first", pend.length
        ? `<ul class="rows">${pend.slice(0, 8).map((x) => `<li>${esc(x.p)}<span class="meta">${esc([x.w.org, x.w.issue_ref ? `issue ${x.w.issue_ref}` : ""].filter(Boolean).join(" ") || "general")}</span></li>`).join("")}</ul>`
        : `<p class="empty">Nothing pending. Enjoy the day.</p>`],
      ["Upcoming reminders", s.reminders.length
        ? `<ul class="rows">${s.reminders.slice(0, 6).map((r) => `<li>${esc(r.text)}<span class="meta">${esc(r.when)}</span></li>`).join("")}</ul>`
        : `<p class="empty">No reminders armed.</p>`],
      ["Fresh updates", fresh.length
        ? `<ul class="rows">${fresh.slice(0, 6).map((c) => `<li>${esc(c.summary)}<span class="meta"><a href="${esc(c.link)}" target="_blank" rel="noopener">open</a></span></li>`).join("")}</ul>`
        : `<p class="empty">Nothing new out there.</p>`],
      ["Suggested next action", next
        ? `<p>${esc(next.p)}</p>`
        : `<p class="empty">All clear.</p>`],
    ];
    sections.forEach(([title, html]) => {
      const div = document.createElement("div");
      div.className = "panel";
      div.innerHTML = `<h3>${title}</h3>${html}`;
      box.appendChild(div);
    });
  }

  /* ---------- wiring ---------- */
  function greeting() {
    const h = new Date().getHours();
    $("greeting").textContent = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    $("dateline").textContent = new Date().toLocaleDateString("en-IN", {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    });
  }

  function applyLang(code) {
    store.lang = code;
    localStorage.setItem("remo-lang", code);
    $("v-lang").textContent = LANG_NAME[code] || code;
    $("ask-lang").textContent = LANG_NAME[code] || code;
    $("set-hi").classList.toggle("on", code === "hi-IN");
    $("set-mr").classList.toggle("on", code === "mr-IN");
  }

  async function loadInfo() {
    try {
      const i = await API.info();
      $("app-info").innerHTML =
        `<dt>Version</dt><dd>${esc(i.version)}</dd><dt>Server language</dt><dd>${esc(i.language)}</dd>` +
        `<dt>Voice</dt><dd>${esc(i.voice)}</dd><dt>STT</dt><dd>${esc(i.stt_model)}</dd><dt>TTS</dt><dd>${esc(i.tts_model)}</dd>`;
    } catch {
      $("app-info").innerHTML = `<dt>Status</dt><dd>Server away</dd>`;
    }
  }

  async function pollAlarms() {
    try {
      const { alarms } = await API.alarms();
      for (const a of alarms || []) {
        toast(`Reminder: ${a.text}`);
        addTurn($("thread-home"), "Remo", `Reminder: ${a.text}`, null);
        try {
          const { audio_url } = await API.speak(`Yaad dila raha hoon: ${a.text}`, store.lang);
          play(audio_url, refresh);
        } catch { /* stay silent on speak failure */ }
      }
      if ((alarms || []).length) refresh();
    } catch { /* ignore */ }
  }

  function init() {
    greeting();
    applyLang(store.lang === "mr-IN" ? "mr-IN" : "hi-IN");
    $("set-autoplay").checked = store.autoplay;
    route();
    idleWave($("v-wave"));

    makeVoice({
      micBtn: $("v-mic"),
      stateEl: $("v-state"),
      timerEl: $("v-timer"),
      heardEl: $("v-heard"),
      waveEl: $("v-wave"),
      box: $("thread-home"),
    });
    makeVoice({
      micBtn: $("ask-mic"),
      stateEl: { set textContent(v) { toast(v); }, classList: { toggle() {} } },
      timerEl: { set hidden(v) {}, set textContent(v) {} },
      heardEl: { set hidden(v) {}, set textContent(v) {} },
      waveEl: null,
      box: $("thread-ask"),
    });

    $("v-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("v-text");
      submitText(input.value, $("thread-home"));
      input.value = "";
    });
    $("ask-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("ask-text");
      submitText(input.value, $("thread-ask"), { quiet: false });
      input.value = "";
    });
    $("mem-search").addEventListener("input", () => store.cache && renderMemories(store.cache));
    $("watch-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = $("watch-url").value.trim();
      if (!url) return;
      try {
        const data = await API.turnText(`watch karo ${url}`, store.lang, null);
        toast(data.text);
        $("watch-url").value = "";
        refresh();
      } catch (err) { toast(`Watch failed: ${err.message}`, true); }
    });
    $("brief-speak").onclick = async () => {
      try {
        const data = await API.turnText("welcome back", store.lang, null);
        toast(data.text);
        play(data.audio_url, () => { refresh(); renderBriefing(); });
      } catch (err) { toast(`Briefing failed: ${err.message}`, true); }
    };
    $("set-hi").onclick = () => applyLang("hi-IN");
    $("set-mr").onclick = () => applyLang("mr-IN");
    $("set-autoplay").onchange = (e) => {
      store.autoplay = e.target.checked;
      localStorage.setItem("remo-autoplay", store.autoplay ? "on" : "off");
    };
    $("seed").onclick = async () => {
      try { await API.seed(); toast("Demo data loaded"); refresh(); }
      catch (err) { toast(`Seed failed: ${err.message}`, true); }
    };
    $("collapse").onclick = () => {
      document.querySelector(".shell").classList.toggle("narrow");
    };
    $("menu-btn").onclick = () => {
      document.querySelector(".shell").classList.add("open");
      $("scrim").hidden = false;
    };
    $("scrim").onclick = () => {
      document.querySelector(".shell").classList.remove("open");
      $("scrim").hidden = true;
    };

    skeleton($("activity"));
    refresh();
    loadInfo();
    setInterval(refresh, 10000);
    setInterval(pollAlarms, 5000);
  }

  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
