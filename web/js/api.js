/* Thin wrappers over Remo's FastAPI backend. No business logic here. */
window.RemoAPI = (() => {
  async function turnText(text, lang, pending, speak = true) {
    const res = await fetch("/api/turn/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang, pending: pending || null, speak }),
    });
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function turnAudio(wavBlob, lang, pending, speak = true) {
    const form = new FormData();
    form.append("file", wavBlob, "turn.wav");
    form.append("lang", lang);
    form.append("pending", JSON.stringify(pending || {}));
    form.append("speak", speak ? "true" : "false");
    const res = await fetch("/api/turn/audio", { method: "POST", body: form });
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function state() {
    const res = await fetch("/api/state");
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function info() {
    const res = await fetch("/api/info");
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function alarms() {
    const res = await fetch("/api/alarms");
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function speak(text, lang) {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang }),
    });
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function seed() {
    const res = await fetch("/api/demo/seed", { method: "POST" });
    if (!res.ok) throw new Error(`server said ${res.status}`);
    return res.json();
  }

  async function remove(kind, id) {
    const res = await fetch(`/api/${kind}/${id}`, { method: "DELETE" });
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch { detail = ""; }
      const err = new Error(detail || `server said ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  return { turnText, turnAudio, state, info, alarms, speak, seed, remove };
})();
