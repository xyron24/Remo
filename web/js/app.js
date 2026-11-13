/* Remo app shell: routing, voice studio widget, inline audio player, pages. Vanilla JS. */
(() => {
  const $ = (id) => document.getElementById(id);
  const API = window.RemoAPI;

  const store = {
    lang: localStorage.getItem("remo-lang") || "hi-IN",
    autoplay: localStorage.getItem("remo-autoplay") !== "off",
    theme: localStorage.getItem("remo-theme") || "light",
    pending: null,
    cache: null,
    activePill: null,
  };
  const LANG_NAME = { "hi-IN": "Hinglish", "mr-IN": "Marathi" };
  const SPEAKER_NAME = { "hi-IN": "Nalini", "mr-IN": "Zahira" };
  const player = new Audio();
  let homeVoice = null;
  let askVoice = null;

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmtTime(ts) {
    return new Date(ts * 1000).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  }
  function cssVar(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
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
    const mark = document.querySelector(".mark");
    if (mark) {
      mark.style.background = state === "speaking"
        ? cssVar("--accent", "#1e563f")
        : state === "thinking"
          ? cssVar("--thinking", "#8c4a1f")
          : cssVar("--bordo", "#6e1d31");
    }
  }
  function clearActivePill() {
    if (store.activePill) {
      store.activePill.classList.remove("playing");
      const useEl = store.activePill.querySelector(".audio-play use");
      if (useEl) useEl.setAttribute("href", "#i-play");
      store.activePill = null;
    }
  }
  function play(url, done, pillEl) {
    if (!url) { done && done(); return; }
    if (!pillEl && !store.autoplay) { done && done(); return; }

    // Toggle off if clicking currently playing pill
    if (pillEl && store.activePill === pillEl && !player.paused) {
      player.pause();
      clearActivePill();
      return;
    }

    clearActivePill();
    if (pillEl) {
      store.activePill = pillEl;
      pillEl.classList.add("playing");
      const useEl = pillEl.querySelector(".audio-play use");
      if (useEl) useEl.setAttribute("href", "#i-pause");
    }

    player.src = url;
    const end = () => {
      clearActivePill();
      done && done();
    };
    player.onended = end;
    player.onerror = end;
    player.play().catch(end);
  }

  /* ---------- router ---------- */
  const PAGES = ["home", "ask", "memories", "work", "reminders", "watchlist", "briefing", "voice", "settings", "profile"];
  function activePage() {
    const raw = location.hash.replace("#/", "").split("?")[0] || "home";
    return PAGES.includes(raw) ? raw : "home";
  }
  function route() {
    const page = activePage();
    PAGES.forEach((p) => { $(`page-${p}`).hidden = p !== page; });
    document.querySelectorAll(".side-nav a").forEach((a) => {
      a.classList.toggle("active", a.dataset.page === page);
    });
    document.querySelector(".shell").classList.remove("open");
    $("scrim").hidden = true;
    if (page === "briefing") renderBriefing();
  }
  window.addEventListener("hashchange", route);

  /* ---------- threads & inline player ---------- */
  const BAR_HEIGHTS = [38, 65, 90, 52, 78, 96, 62, 44, 84, 72, 48, 88, 66, 36];
  async function speakInBackground(text, pill, done) {
    try {
      const { audio_url } = await API.speak(text, store.lang);
      if (pill) {
        const btn = pill.querySelector("button");
        if (btn) btn.onclick = () => play(audio_url, null, pill);
      }
      play(audio_url, done, pill);
    } catch (err) {
      toast(`Voice reply failed: ${err.message}`, true);
      done && done();
    }
  }

  function buildAudioPill(url, text) {
    const pill = document.createElement("div");
    pill.className = "audio-pill";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "audio-play";
    btn.setAttribute("aria-label", "Play or pause voice reply");
    btn.innerHTML = `<svg><use href="#i-play"/></svg>`;

    const bars = document.createElement("div");
    bars.className = "audio-bars";
    bars.setAttribute("aria-hidden", "true");
    BAR_HEIGHTS.forEach((h) => {
      const i = document.createElement("i");
      i.style.height = `${h}%`;
      bars.appendChild(i);
    });

    const meta = document.createElement("span");
    meta.className = "audio-meta";
    meta.textContent = `Timbre · ${store.voice || SPEAKER_NAME[store.lang] || "Nalini"}`;

    pill.appendChild(btn);
    pill.appendChild(bars);
    pill.appendChild(meta);

    if (url) {
      btn.onclick = () => play(url, null, pill);
    } else {
      btn.onclick = () => speakInBackground(text, pill, null);
    }
    return pill;
  }

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

  const ACTION_LABELS = {
    saved: "saved",
    recall: "recall",
    chat: "chat",
    task_added: "task",
    task_ask: "confirm",
    briefing: "briefing",
    plan: "day plan",
    remind_ask: "confirm",
    remind_set: "reminder",
    quiz_ask: "quiz",
    quiz_grade: "quiz",
    watch: "watching",
    undo_ask: "confirm",
    forget_ask: "confirm",
    undone: "undone",
    repeat: "repeat",
  };

  function addTurn(box, who, text, data) {
    const div = document.createElement("div");
    div.className = `turn${who === "You" ? " you" : ""}`;

    const tag = data && data.action && ACTION_LABELS[data.action]
      ? `<span class="action-tag${data.action.includes("ask") || data.action === "repeat" ? " warn" : ""}">${esc(ACTION_LABELS[data.action])}</span>`
      : "";

    let html = `<div class="turn-head"><div class="who">${who}</div>${tag}</div><p>${esc(text)}</p>`;
    if (data && data.links && data.links.length) {
      html += `<div class="links">${data.links.map((l) =>
        `<a href="${esc(l)}" target="_blank" rel="noopener">${esc(shortUrl(l))} ↗</a>`).join("")}</div>`;
    }
    div.innerHTML = html;

    let pill = null;
    if (data && (data.audio_url || who === "Remo")) {
      pill = buildAudioPill(data.audio_url || null, text);
      div.appendChild(pill);
    }
    if (data) pendingChips(data, div);
    box.prepend(div);
    while (box.children.length > 30) box.lastChild.remove();
    return pill;
  }

  async function submitText(text, box, opts = {}) {
    const value = (text || "").trim();
    if (!value) return;
    setSide("thinking", "Thinking");
    try {
      const data = await API.turnText(value, store.lang, store.pending, false);
      store.pending = data.pending || null;
      showPendingChip();
      addTurn(box, "You", value, null);
      const pill = addTurn(box, "Remo", data.text, data);
      refresh();
      if (!opts.quiet && store.autoplay) {
        setSide("speaking", "Speaking");
        speakInBackground(data.text, pill, () => { setSide("ready", "Ready"); refresh(); });
      } else {
        setSide("ready", "Ready");
      }
    } catch (err) {
      toast(`Send failed: ${err.message}`, true);
      setSide("bad", "Error");
    }
  }

  function showPendingChip() {
    const el = $("v-pending");
    if (!store.pending || !store.pending.action) { el.hidden = true; return; }
    const labels = {
      undo: "waiting: forget last? (haan / nahi)",
      forget: "waiting: forget this? (haan / nahi)",
      remind: "waiting: arm reminder? (haan / nahi)",
      remind_ask: "waiting: what for?",
      quiz: "quiz live: answer or say bas",
    };
    el.textContent = labels[store.pending.action] || "waiting";
    el.hidden = false;
  }

  /* ---------- voice widget ---------- */
  function makeVoice({ micBtn, cardEl, stateEl, timerEl, heardEl, waveEl, box, autoPlay = true }) {
    const session = window.RemoVoice.createSession({
      onLevel: (data) => drawWave(waveEl, data, true),
      onDone: async (wav) => {
        stopTimer();
        if (cardEl) cardEl.classList.remove("is-live");
        idleWave(waveEl);
        setState("processing", "Thinking…");
        setSide("thinking", "Thinking");
        try {
          const data = await API.turnAudio(wav, store.lang, store.pending, false);
          store.pending = data.pending || null;
          showPendingChip();
          if (data.transcript) {
            heardEl.textContent = `Heard: "${data.transcript}"`;
            heardEl.hidden = false;
            addTurn(box, "You", data.transcript, null);
          }
          const pill = addTurn(box, "Remo", data.text, data);
          setState("responding", "Here is what I found");
          setSide("speaking", "Speaking");
          const end = () => {
            setState("idle", "Tap the mic or press Space to talk");
            setSide("ready", "Ready");
            refresh();
          };
          if (autoPlay && store.autoplay) {
            speakInBackground(data.text, pill, end);
          } else {
            end();
          }
        } catch (err) {
          setState("error", `Could not reach Remo (${err.message})`);
          setSide("bad", "Error");
          toast(`Voice turn failed: ${err.message}`, true);
        }
      },
      onError: (err) => {
        stopTimer();
        if (cardEl) cardEl.classList.remove("is-live");
        idleWave(waveEl);
        setState("error", `Recording failed (${err.message})`);
        setSide("bad", "Error");
      },
    });

    let timer = 0, timerInt = 0;
    function startTimer() {
      timer = 0;
      timerEl.hidden = false;
      timerEl.textContent = "0:00";
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
        if (cardEl) cardEl.classList.add("is-live");
        setState("listening", "Listening… tap mic or press Space when done");
        setSide("listening", "Listening");
      } catch (err) {
        setState("error", `Microphone blocked (${err.message})`);
        toast("Allow microphone access and retry", true);
      }
    }
    micBtn.onclick = toggle;
    return { toggle };
  }

  /* ---------- crisp capsule waveform canvas ---------- */
  function prepCanvas(canvas) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(240, Math.round(rect.width || 520));
    const h = Math.max(48, Math.round(rect.height || 60));
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, W: w, H: h };
  }

  function roundPill(ctx, x, y, w, h) {
    const r = Math.min(w / 2, h / 2);
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(x, y, w, h, r) : ctx.rect(x, y, w, h);
    ctx.fill();
  }

  function drawWave(canvas, data, live) {
    if (!canvas) return;
    const { ctx, W, H } = prepCanvas(canvas);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = live ? cssVar("--listening", "#87253e") : cssVar("--accent", "#1e563f");
    const n = 52, gap = W / n, bw = Math.max(3, gap * 0.48);
    for (let i = 0; i < n; i++) {
      const v = data[Math.floor((i / n) * data.length * 0.7)] / 255;
      const h = Math.max(4, v * (H - 12));
      roundPill(ctx, i * gap + (gap - bw) / 2, (H - h) / 2, bw, h);
    }
  }

  function idleWave(canvas) {
    if (!canvas) return;
    const { ctx, W, H } = prepCanvas(canvas);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = cssVar("--border-strong", "rgba(43, 25, 29, 0.25)");
    const n = 52, gap = W / n, bw = Math.max(3, gap * 0.44);
    for (let i = 0; i < n; i++) {
      const h = 4 + 4.5 * Math.abs(Math.sin(i * 0.38));
      roundPill(ctx, i * gap + (gap - bw) / 2, (H - h) / 2, bw, h);
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
      $("conn").className = "conn-dot ready";
      $("conn").title = "Connected";
    } catch {
      $("conn").className = "conn-dot bad";
      $("conn").title = "Server away";
    }
  }

  function avatarHTML(me, fallback) {
    if (me && me.avatar_url) return `<img src="${esc(me.avatar_url)}" alt="">`;
    return esc(fallback);
  }

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  function setHTML(id, value) {
    const el = $(id);
    if (el) el.innerHTML = value;
  }

  function renderMe() {
    const me = store.me || {};
    const initial = (me.name || me.email || "?").trim().charAt(0).toUpperCase() || "?";
    setHTML("chip-avatar", avatarHTML(me, initial));
    setText("chip-name", me.name || me.email || "…");
    setHTML("prof-avatar", avatarHTML(me, initial));
    setText("prof-name", me.name || "…");
    setText("prof-email", me.email || "");
    setText("prof-provider", me.provider === "google" ? "Google" : "Email");
    setText("prof-since", me.created_at
      ? `member since ${new Date(me.created_at * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}`
      : "");
  }

  function renderProfileStats(s) {
    const el = $("prof-stats");
    if (!el || !s) return;
    el.textContent = `${s.notes.length} memories · ${pendingCount(s)} pending · ${s.reminders.length} alarms · ${s.watched.length} watched`;
  }

  function pendingCount(s) {
    return s.work.reduce((a, w) => a + w.pending.length, 0);
  }

  function badge(id, n) {
    const el = $(id);
    if (!el) return;
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
      ...s.notes.slice(0, 4).map((n) => ({ text: n.text, meta: `memory · ${fmtTime(n.created_at)}` })),
      ...s.reminders.slice(0, 3).map((r) => ({ text: r.text, meta: `alarm · ${r.when}` })),
      ...s.changes.slice(0, 3).map((c) => ({ text: c.summary, meta: "watcher update" })),
    ].slice(0, 8);
    if (!items.length) act.innerHTML = `<li class="empty">Quiet so far. Click a sample phrase above or tap the mic to begin.</li>`;
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
    renderLearned(s);
    renderProfileStats(s);
  }

  async function removeItem(kind, id, label) {
    if (!window.confirm(`Delete this ${label}? This cannot be undone.`)) return;
    try {
      await API.remove(kind, id);
      toast("Deleted");
    } catch (err) {
      if (err.status === 404 && /no such/.test(err.message)) {
        toast("That item is already gone");
      } else if (err.status === 404) {
        toast("Delete needs a server restart: stop uvicorn (Ctrl+C) and start it again", true);
        return;
      } else {
        toast(`Delete failed: ${err.message}`, true);
        return;
      }
    }
    refresh();
  }

  function delButton(kind, id, label) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "del-btn";
    b.title = `Delete this ${label}`;
    b.setAttribute("aria-label", `Delete this ${label}`);
    b.innerHTML = `<svg><use href="#i-x"/></svg>`;
    b.onclick = (e) => { e.stopPropagation(); removeItem(kind, id, label); };
    return b;
  }

  function renderMemories(s) {
    const q = ($("mem-search").value || "").toLowerCase();
    const list = $("mem-list");
    const hits = s.notes.filter((n) => !q || n.text.toLowerCase().includes(q));
    list.innerHTML = hits.length ? "" : `<li class="empty">${s.notes.length ? "No matches." : "No memories yet. Say: yaad rakhna ..."}</li>`;
    hits.slice(0, 60).forEach((n) => {
      const li = document.createElement("li");
      li.className = "deletable";
      li.innerHTML = `${esc(n.text)}<span class="meta">${esc(fmtTime(n.created_at))} · ${esc(n.source || "voice")}</span>`;
      li.appendChild(delButton("notes", n.id, "memory"));
      list.appendChild(li);
    });
  }

  function renderWork(s) {
    const box = $("work-list");
    box.innerHTML = s.work.length ? "" : `<div class="panel"><p class="empty">No work tracked. Speak a progress update (e.g. “Yaad rakhna, issue 214: login fix ho gaya, docs baaki hai”).</p></div>`;
    s.work.forEach((w) => {
      const label = [w.org, w.issue_ref ? `issue ${w.issue_ref}` : ""].filter(Boolean).join(" ") || "general";
      const total = w.done.length + w.pending.length;
      const pct = total ? Math.round((w.done.length / total) * 100) : 0;
      const div = document.createElement("div");
      div.className = "panel deletable";
      const pend = w.pending.map((p) => `<li class="pend-item">${esc(p)}</li>`).join("") || `<li class="empty">Nothing pending.</li>`;
      const done = w.done.map((d) => `<li class="done-item">${esc(d)}</li>`).join("") || `<li class="empty">Nothing done yet.</li>`;
      div.innerHTML = `<h3>${esc(label)} <span class="persona-pill">${esc(w.persona)} · ${w.done.length}/${total} done</span></h3>
        <div class="work-progress" aria-hidden="true"><i style="width:${pct}%"></i></div>
        <ul class="rows">${pend}</ul><ul class="rows" style="margin-top:.55rem">${done}</ul>`;
      div.appendChild(delButton("work", w.id, "work entry"));
      box.appendChild(div);
    });
  }

  function renderReminders(s) {
    const up = $("rem-list"), done = $("rem-done");
    up.innerHTML = s.reminders.length ? "" : `<li class="empty">None armed.</li>`;
    s.reminders.forEach((r) => {
      const li = document.createElement("li");
      li.className = "deletable";
      li.innerHTML = `${esc(r.text)}<span class="meta">${esc(r.when)}</span>`;
      li.appendChild(delButton("reminders", r.id, "reminder"));
      up.appendChild(li);
    });
    done.innerHTML = s.reminders_fired.length ? "" : `<li class="empty">None completed yet.</li>`;
    s.reminders_fired.slice(0, 20).forEach((r) => {
      const li = document.createElement("li");
      li.className = "deletable";
      li.innerHTML = `${esc(r.text)}<span class="meta">fired ${esc(r.when)}</span>`;
      li.appendChild(delButton("reminders", r.id, "reminder"));
      done.appendChild(li);
    });
  }

  function renderWatch(s) {
    const box = $("watch-list");
    box.innerHTML = s.watched.length ? "" : `<div class="panel"><p class="empty">Nothing watched. Paste a GitHub link above, or say: watch karo ...</p></div>`;
    s.watched.forEach((w) => {
      const fresh = s.changes.filter((c) => c.watch_url === w.url).slice(0, 4);
      const div = document.createElement("div");
      div.className = "panel deletable";
      div.innerHTML = `<h3><a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(shortUrl(w.url))}</a>
        ${fresh.some((c) => !c.briefed) ? `<span class="pill-new">new</span>` : ""}</h3>
        <p class="muted small">Last checked: ${w.checked_at ? esc(fmtTime(w.checked_at)) : "never"}</p>
        <ul class="rows">${fresh.length ? fresh.map((c) =>
          `<li>${esc(c.summary)}<span class="meta"><a href="${esc(c.link)}" target="_blank" rel="noopener">open source ↗</a></span></li>`
        ).join("") : `<li class="empty">No changes recorded yet.</li>`}</ul>`;
      div.appendChild(delButton("watch", w.id, "watched item"));
      box.appendChild(div);
    });
  }

  function renderLearned(s) {
    const wordsEl = $("learned-words");
    const rulesEl = $("learned-rules");
    if (!wordsEl || !rulesEl) return;
    const learned = s.learned || {};
    const words = learned.boost_words || [];
    const rules = learned.fix_rules || [];
    wordsEl.innerHTML = words.length
      ? words.slice(0, 24).map((w) => `<span class="learned-chip">${esc(w)}</span>`).join("")
      : `<span class="muted small">No custom boost words yet — save a few notes to populate.</span>`;
    rulesEl.innerHTML = rules.length
      ? `<strong>Fix rules:</strong> ` + rules.map(([a, b]) => `<code>${esc(a)} → ${esc(b)}</code>`).join(" ")
      : "";
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
      li.innerHTML = `${esc(c.summary)}<span class="meta"><a href="${esc(c.link)}" target="_blank" rel="noopener">open ↗</a></span>`;
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
        ? `<ul class="rows">${fresh.slice(0, 6).map((c) => `<li>${esc(c.summary)}<span class="meta"><a href="${esc(c.link)}" target="_blank" rel="noopener">open ↗</a></span></li>`).join("")}</ul>`
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
    if ($("v-lang-hi")) $("v-lang-hi").classList.toggle("on", code === "hi-IN");
    if ($("v-lang-mr")) $("v-lang-mr").classList.toggle("on", code === "mr-IN");
  }

  function applyTheme(theme) {
    store.theme = theme === "dark" ? "dark" : "light";
    localStorage.setItem("remo-theme", store.theme);
    if (store.theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
    idleWave($("v-wave"));
  }

  async function loadInfo() {
    try {
      const i = await API.info();
      store.voice = i.voice || null;
      document.querySelectorAll(".audio-meta").forEach((el) => {
        el.textContent = `Timbre · ${store.voice}`;
      });
      if (i.voices) {
        if ($("voice-hi")) $("voice-hi").textContent = i.voices["hi-IN"] || "";
        if ($("voice-mr")) $("voice-mr").textContent = i.voices["mr-IN"] || "";
      }
      const pretty = (m) => {
        if (!m) return "";
        const [name, ...rest] = m.split("-");
        return name.charAt(0).toUpperCase() + name.slice(1) + (rest.length ? ` ${rest.join("-")}` : "");
      };
      if ($("model-pill") && i.stt_model && i.tts_model) {
        $("model-pill").textContent = `${pretty(i.stt_model)} · ${pretty(i.tts_model)}`;
      }
      if ($("voice-models-line") && i.stt_model && i.tts_model) {
        $("voice-models-line").textContent =
          `How Remo listens via ${pretty(i.stt_model)}, speaks via ${pretty(i.tts_model)}, and adapts to your vocabulary.`;
      }
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
        const pill = addTurn($("thread-home"), "Remo", `Reminder: ${a.text}`, { action: "remind_set" });
        try {
          const { audio_url } = await API.speak(`Yaad dila raha hoon: ${a.text}`, store.lang);
          play(audio_url, refresh, pill);
        } catch { /* stay silent on speak failure */ }
      }
      if ((alarms || []).length) refresh();
    } catch { /* ignore */ }
  }

  function runBriefingAction() {
    return submitText("welcome back", $("thread-home"));
  }

  async function init() {
    try {
      store.me = (await API.me()).user;
    } catch (err) {
      if (err && err.message === "signed out") return; // req() redirected to /login
      // Anything else (e.g. talking to an older server): run degraded, profile blank.
    }
    try {
      renderMe();
    } catch {
      /* mismatched markup must never kill the app */
    }
    greeting();
    applyTheme(store.theme);
    applyLang(store.lang === "mr-IN" ? "mr-IN" : "hi-IN");
    $("set-autoplay").checked = store.autoplay;
    route();
    idleWave($("v-wave"));

    homeVoice = makeVoice({
      micBtn: $("v-mic"),
      cardEl: $("voice-card"),
      stateEl: $("v-state"),
      timerEl: $("v-timer"),
      heardEl: $("v-heard"),
      waveEl: $("v-wave"),
      box: $("thread-home"),
    });
    askVoice = makeVoice({
      micBtn: $("ask-mic"),
      cardEl: null,
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
    if ($("watch-check-btn")) {
      $("watch-check-btn").onclick = async () => {
        try {
          const data = await API.turnText("koi update aaya?", store.lang, null);
          toast(data.text);
          if (data.audio_url) play(data.audio_url, refresh);
          else refresh();
        } catch (err) { toast(`Check failed: ${err.message}`, true); }
      };
    }
    $("brief-speak").onclick = async () => {
      try {
        const data = await API.turnText("welcome back", store.lang, null);
        toast(data.text);
        play(data.audio_url, () => { refresh(); renderBriefing(); });
      } catch (err) { toast(`Briefing failed: ${err.message}`, true); }
    };
    if ($("ctx-brief-btn")) $("ctx-brief-btn").onclick = runBriefingAction;

    $("set-hi").onclick = () => applyLang("hi-IN");
    $("set-mr").onclick = () => applyLang("mr-IN");
    if ($("v-lang-hi")) $("v-lang-hi").onclick = () => applyLang("hi-IN");
    if ($("v-lang-mr")) $("v-lang-mr").onclick = () => applyLang("mr-IN");
    $("set-autoplay").onchange = (e) => {
      store.autoplay = e.target.checked;
      localStorage.setItem("remo-autoplay", store.autoplay ? "on" : "off");
    };

    const doSeed = async () => {
      try { await API.seed(); toast("Demo data loaded"); refresh(); }
      catch (err) { toast(`Seed failed: ${err.message}`, true); }
    };
    $("seed").onclick = doSeed;
    if ($("logout-btn")) $("logout-btn").onclick = async () => {
      try { await API.logout(); } catch { /* cookie cleared anyway */ }
      window.location.href = "/login";
    };
    wirePdfImport();
    if (!window.__remoErrWired) {
      window.__remoErrWired = true;
      window.addEventListener("error", () => {
        toast("The app hit an error. Hard-refresh (Cmd+Shift+R) to reload it cleanly.", true);
      }, { once: true });
    }

    if ($("try-chips")) {
      $("try-chips").addEventListener("click", (e) => {
        const btn = e.target.closest(".try-chip");
        if (!btn) return;
        const prompt = btn.dataset.prompt;
        if (prompt) submitText(prompt, $("thread-home"));
      });
    }

    if ($("theme-toggle")) {
      $("theme-toggle").onclick = () => applyTheme(store.theme === "dark" ? "light" : "dark");
    }

    $("collapse").onclick = () => {
      document.querySelector(".shell").classList.toggle("narrow");
      setTimeout(() => idleWave($("v-wave")), 40);
    };
    $("menu-btn").onclick = () => {
      document.querySelector(".shell").classList.add("open");
      $("scrim").hidden = false;
    };
    $("scrim").onclick = () => {
      document.querySelector(".shell").classList.remove("open");
      $("scrim").hidden = true;
    };

    // Spacebar / M push-to-toggle mic when not typing
    window.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable)) return;
      if (e.code === "Space" || (e.key && e.key.toLowerCase() === "m" && !e.metaKey && !e.ctrlKey)) {
        const page = activePage();
        if (page === "home" && homeVoice) { e.preventDefault(); homeVoice.toggle(); }
        else if (page === "ask" && askVoice) { e.preventDefault(); askVoice.toggle(); }
      }
    });

    window.addEventListener("resize", () => idleWave($("v-wave")));

    // Support ?say=... deep link from landing page
    const params = new URLSearchParams(window.location.search);
    const say = params.get("say");
    if (say && $("v-text")) {
      $("v-text").value = say;
      $("v-text").focus();
      toast("Phrase loaded — press Enter to run");
    }

    wireOverviewLink();

    skeleton($("activity"));
    refresh();
    loadInfo();
    setInterval(refresh, 10000);
    setInterval(pollAlarms, 5000);
  }

  let importSource = "";
  function wirePdfImport() {
    const btn = $("import-pdf-btn"), file = $("import-pdf-file");
    if (!btn || !file || btn.dataset.wired) return;
    btn.dataset.wired = "1";
    btn.onclick = () => file.click();
    file.onchange = async () => {
      if (!file.files.length) return;
      btn.disabled = true;
      toast("Reading PDF, this takes a few seconds…");
      try {
        const data = await API.importPdf(file.files[0]);
        importSource = data.filename || file.files[0].name;
        renderImportPick(data.notes || []);
      } catch (err) {
        toast(err.message, true);
      } finally {
        btn.disabled = false;
        file.value = "";
      }
    };
    $("import-cancel-btn").onclick = () => { $("import-pick").hidden = true; };
    $("import-keep-btn").onclick = async () => {
      const picked = [...document.querySelectorAll("#import-list input:checked")]
        .map((box) => box.value);
      if (!picked.length) { toast("Tick at least one note", true); return; }
      try {
        const done = await API.keepNotes(picked, importSource);
        toast(`Saved ${done.saved} notes from PDF`);
        $("import-pick").hidden = true;
        refresh();
      } catch (err) {
        toast(err.message, true);
      }
    };
  }

  function renderImportPick(notes) {
    const box = $("import-pick"), list = $("import-list");
    list.innerHTML = "";
    if (!notes.length) { toast("No notes found in that PDF", true); return; }
    notes.forEach((text, i) => {
      const li = document.createElement("li");
      const id = `imp-${i}`;
      li.innerHTML = `<label class="check" for="${id}"><input id="${id}" type="checkbox" checked value="${esc(text)}"><span>${esc(text)}</span></label>`;
      list.appendChild(li);
    });
    box.hidden = false;
  }

  function wireOverviewLink() {
    const link = $("nav-overview");
    if (!link || link.dataset.wired) return;
    link.dataset.wired = "1";
    link.addEventListener("click", (e) => {
      e.preventDefault();
      document.querySelector(".shell").classList.add("leaving");
      setTimeout(() => { window.location.href = "/"; }, 170);
    });
  }

  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
