/* Thin wrappers over Remo's FastAPI backend. No business logic here. */
window.RemoAPI = (() => {
  async function req(url, opts) {
    const res = await fetch(url, opts);
    if (res.status === 401 && !url.startsWith("/api/auth/")) {
      window.location.href = "/login";
      throw new Error("signed out");
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch { detail = ""; }
      throw new Error(detail || `server said ${res.status}`);
    }
    return res;
  }

  async function turnText(text, lang, pending, speak = true) {
    const res = await req("/api/turn/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang, pending: pending || null, speak }),
    });
    return res.json();
  }

  async function turnAudio(wavBlob, lang, pending, speak = true) {
    const form = new FormData();
    form.append("file", wavBlob, "turn.wav");
    form.append("lang", lang);
    form.append("pending", JSON.stringify(pending || {}));
    form.append("speak", speak ? "true" : "false");
    const res = await req("/api/turn/audio", { method: "POST", body: form });
    return res.json();
  }

  async function state() {
    return (await req("/api/state")).json();
  }

  async function info() {
    return (await req("/api/info")).json();
  }

  async function alarms() {
    return (await req("/api/alarms")).json();
  }

  async function speak(text, lang) {
    const res = await req("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang }),
    });
    return res.json();
  }

  async function seed() {
    const res = await req("/api/demo/seed", { method: "POST" });
    return res.json();
  }

  async function me() {
    return (await req("/api/me")).json();
  }

  async function logout() {
    const res = await req("/api/logout", { method: "POST" });
    return res.json();
  }

  async function importPdf(file) {
    const form = new FormData();
    form.append("file", file, file.name);
    const res = await req("/api/import/pdf", { method: "POST", body: form });
    return res.json();
  }

  async function keepNotes(notes, source) {
    const res = await req("/api/import/keep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes, source }),
    });
    return res.json();
  }

  async function remove(kind, id) {
    const res = await fetch(`/api/${kind}/${id}`, { method: "DELETE" });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("signed out");
    }
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch { detail = ""; }
      const err = new Error(detail || `server said ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  return { turnText, turnAudio, state, info, alarms, speak, seed, me, logout, remove, importPdf, keepNotes };
})();
