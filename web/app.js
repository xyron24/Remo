/* Remo browser loop: record -> 16kHz WAV -> server -> spoken reply. */
(() => {
  const dot = document.getElementById("dot");
  const status = document.getElementById("status");
  const mic = document.getElementById("mic");
  const micwrap = document.querySelector(".micwrap");
  const wave = document.getElementById("wave");
  const thread = document.getElementById("thread");
  const pendingChip = document.getElementById("pending");
  const langHi = document.getElementById("lang-hi");
  const langMr = document.getElementById("lang-mr");
  const seedBtn = document.getElementById("seed");
  const wctx = wave.getContext("2d");

  let lang = localStorage.getItem("remo-lang") || "hi-IN";
  let pending = null;
  let recorder = null;
  let parts = [];
  let recording = false;
  let analyser = null;
  let vizId = null;
  const player = new Audio();

  const OLIVE = "#4f5b3a";
  const CLAY = "#c67c4e";
  const STONE = "#d1d4c5";

  function setLang(code) {
    lang = code;
    localStorage.setItem("remo-lang", code);
    langHi.classList.toggle("on", code === "hi-IN");
    langMr.classList.toggle("on", code === "mr-IN");
  }
  setLang(lang === "mr-IN" ? "mr-IN" : "hi-IN");
  langHi.onclick = () => setLang("hi-IN");
  langMr.onclick = () => setLang("mr-IN");

  function setStatus(mode, text) {
    dot.className = `dot ${mode}`;
    status.textContent = text;
  }

  function showPending() {
    if (!pending || !pending.action) { pendingChip.hidden = true; return; }
    const labels = { undo: "waiting: forget last? (haan / nahi)", forget: "waiting: forget this? (haan / nahi)",
      remind: "waiting: arm reminder? (haan / nahi)", remind_ask: "waiting: what for?",
      quiz: "quiz live — answer or say “bas”" };
    pendingChip.textContent = labels[pending.action] || "waiting…";
    pendingChip.hidden = false;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function addTurn(who, text, links, audioUrl) {
    const div = document.createElement("div");
    div.className = `turn${who === "You" ? " you" : ""}`;
    let html = `<div class="who">${who}</div><p>${esc(text)}</p>`;
    if (links && links.length) {
      html += links.map((l) => `<a href="${esc(l)}" target="_blank" rel="noopener">source</a>`).join(" · ");
    }
    if (audioUrl) html += `<br><button class="replay" type="button" data-url="${esc(audioUrl)}">replay voice</button>`;
    div.innerHTML = html;
    div.querySelectorAll(".replay").forEach((b) => { b.onclick = () => play(b.dataset.url); });
    thread.prepend(div);
    while (thread.children.length > 30) thread.lastChild.remove();
  }

  function idleWave() {
    const W = wave.width, H = wave.height;
    wctx.clearRect(0, 0, W, H);
    wctx.fillStyle = STONE;
    const n = 48, bw = W / n;
    for (let i = 0; i < n; i++) {
      const h = 3 + 2 * Math.sin(i * 0.7);
      wctx.fillRect(i * bw + bw * 0.25, (H - h) / 2, bw * 0.5, h);
    }
  }

  function drawLive(color) {
    const W = wave.width, H = wave.height;
    const data = new Uint8Array(analyser.frequencyBinCount);
    const render = () => {
      if (!analyser) return;
      analyser.getByteFrequencyData(data);
      wctx.clearRect(0, 0, W, H);
      wctx.fillStyle = color;
      const n = 48, bw = W / n;
      for (let i = 0; i < n; i++) {
        const v = data[Math.floor((i / n) * data.length * 0.7)] / 255;
        const h = Math.max(3, v * (H - 8));
        wctx.fillRect(i * bw + bw * 0.25, (H - h) / 2, bw * 0.5, h);
      }
      vizId = requestAnimationFrame(render);
    };
    render();
  }

  function stopViz() {
    if (vizId) cancelAnimationFrame(vizId);
    vizId = null;
    analyser = null;
    idleWave();
  }

  function play(url, done) {
    if (!url) { done && done(); return; }
    setStatus("speaking", "Speaking…");
    player.src = url;
    const end = () => { setStatus("ready", "Ready — press the mic and speak"); done && done(); };
    player.onended = end;
    player.onerror = end;
    player.play().catch(end);
  }

  async function sendTurn(url, form) {
    setStatus("thinking", "Thinking…");
    mic.disabled = true;
    try {
      const res = await fetch(url, { method: "POST", body: form });
      if (!res.ok) throw new Error(`server said ${res.status}`);
      const data = await res.json();
      pending = data.pending || null;
      showPending();
      if (data.transcript) addTurn("You", data.transcript, null, null);
      addTurn("Remo", data.text, data.links, data.audio_url);
      play(data.audio_url, refresh);
    } catch (err) {
      setStatus("ready", "Ready — press the mic and speak");
      addTurn("Remo", `Sorry, that failed (${err.message}). Is the server running with a key?`, null, null);
    } finally {
      mic.disabled = false;
    }
  }

  function encodeWav(samples, rate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const wstr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    wstr(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); wstr(8, "WAVEfmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true); wstr(36, "data"); v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  async function to16kWav(blob) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    try {
      const raw = await blob.arrayBuffer();
      const decoded = await ctx.decodeAudioData(raw);
      const target = new OfflineAudioContext(1, Math.ceil((decoded.duration || 1) * 16000), 16000);
      const src = target.createBufferSource();
      src.buffer = decoded;
      src.connect(target.destination);
      src.start();
      const out = await target.startRendering();
      return encodeWav(out.getChannelData(0), 16000);
    } finally {
      ctx.close();
    }
  }

  async function startRec() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const actx = new (window.AudioContext || window.webkitAudioContext)();
    const src = actx.createMediaStreamSource(stream);
    analyser = actx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) drawLive(OLIVE);
    parts = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      actx.close().catch(() => {});
      stopViz();
      try {
        const wav = await to16kWav(new Blob(parts, { type: recorder.mimeType || "audio/webm" }));
        const form = new FormData();
        form.append("file", wav, "turn.wav");
        form.append("lang", lang);
        form.append("pending", JSON.stringify(pending || {}));
        await sendTurn("/api/turn/audio", form);
      } catch (err) {
        setStatus("ready", "Ready — press the mic and speak");
        addTurn("Remo", `Recording failed (${err.message}).`, null, null);
      }
    };
    recorder.start();
    recording = true;
    mic.classList.add("live");
    micwrap.classList.add("live");
    setStatus("listening", "Listening… press again to stop");
  }

  function stopRec() {
    recording = false;
    mic.classList.remove("live");
    micwrap.classList.remove("live");
    if (recorder && recorder.state !== "inactive") recorder.stop();
    else { stopViz(); setStatus("ready", "Ready — press the mic and speak"); }
  }

  mic.onclick = async () => {
    if (recording) { stopRec(); return; }
    try { await startRec(); }
    catch (err) {
      stopViz();
      setStatus("ready", "Ready — press the mic and speak");
      addTurn("Remo", `Microphone blocked (${err.message}). Allow mic access and retry.`, null, null);
    }
  };

  async function refresh() {
    try {
      const res = await fetch("/api/state");
      if (!res.ok) return;
      const s = await res.json();
      document.getElementById("stat-notes").textContent = s.notes.length;
      document.getElementById("stat-pending").textContent = s.work.reduce((a, w) => a + w.pending.length, 0);
      document.getElementById("stat-rem").textContent = s.reminders.length;
      document.getElementById("stat-watch").textContent = s.watched.length;
      const put = (id, items, render, empty) => {
        const el = document.getElementById(id);
        el.innerHTML = items.length ? "" : `<li class="empty">${empty}</li>`;
        items.slice(0, 12).forEach((it) => {
          const li = document.createElement("li");
          li.innerHTML = render(it);
          el.appendChild(li);
        });
      };
      put("timeline", s.notes, (n) => `${esc(n.text)}<span class="meta">${esc(new Date(n.created_at * 1000).toLocaleString())}</span>`, "Nothing saved yet.");
      put("reminders", s.reminders, (r) => `${esc(r.text)}<span class="meta">${esc(r.when)}</span>`, "None armed.");
      put("work", s.work, (w) => {
        const label = [w.org, w.issue_ref ? `issue ${w.issue_ref}` : ""].filter(Boolean).join(" ") || "general";
        return `${esc(label)}: ${w.pending.length} pending, ${w.done.length} done`;
      }, "No work tracked.");
      put("watched", s.watched, (w) => `<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.url)}</a>`, "Nothing watched.");
      const learned = document.getElementById("learned");
      const words = (s.learned.boost_words || []).slice(0, 12);
      const fixes = (s.learned.fix_rules || []).length;
      learned.textContent = words.length
        ? `Boosting: ${words.join(", ")}${fixes ? ` · ${fixes} fixes` : ""}`
        : "Remo learns your words as you speak.";
      learned.classList.toggle("empty", !words.length);
    } catch { /* server away; leave panels as-is */ }
  }

  async function pollAlarms() {
    try {
      const res = await fetch("/api/alarms");
      if (!res.ok) return;
      const { alarms } = await res.json();
      for (const a of alarms || []) {
        addTurn("Remo", `Reminder: ${a.text}`, null, null);
        const speak = await fetch("/api/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: `Yaad dila raha hoon: ${a.text}`, lang }),
        });
        if (speak.ok) {
          const { audio_url } = await speak.json();
          play(audio_url, refresh);
        }
      }
      if ((alarms || []).length) refresh();
    } catch { /* ignore */ }
  }

  seedBtn.onclick = async () => {
    await fetch("/api/demo/seed", { method: "POST" });
    refresh();
  };

  idleWave();
  refresh();
  setInterval(refresh, 10000);
  setInterval(pollAlarms, 5000);
})();
