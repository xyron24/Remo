/* Voice capture: live 16kHz PCM streaming over WebSocket, MediaRecorder upload fallback. */
window.RemoVoice = (() => {
  const WORKLET_CODE = `
    class RemoTap extends AudioWorkletProcessor {
      constructor() {
        super();
        this.ratio = (sampleRate || 48000) / 16000;
        this.buf = [];
      }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;
        for (let i = 0; i < ch.length; i += this.ratio) {
          const idx = Math.floor(i), frac = i - idx;
          const a = ch[idx] || 0, b = ch[idx + 1] || 0;
          this.buf.push(a + (b - a) * frac);
          if (this.buf.length >= 1600) {
            const out = new Int16Array(1600);
            for (let j = 0; j < 1600; j++) {
              const s = Math.max(-1, Math.min(1, this.buf[j]));
              out[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
            }
            this.port.postMessage(out.buffer, [out.buffer]);
            this.buf.splice(0, 1600);
          }
        }
        return true;
      }
    }
    registerProcessor("remo-tap", RemoTap);
  `;

  let workletUrl = null;
  function tapModuleUrl() {
    if (!workletUrl) {
      workletUrl = URL.createObjectURL(new Blob([WORKLET_CODE], { type: "application/javascript" }));
    }
    return workletUrl;
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

  async function to16kWav(blob, mimeType) {
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

  function createSession({ onLevel, onDone, onError, onPartial, onResult }) {
    let stream = null, recorder = null, actx = null, analyser = null, raf = 0;
    let parts = [];
    let live = false;
    let mode = null;
    let ws = null, tapNode = null, resultTimer = 0, gotResult = false;

    function tick() {
      if (!live || !analyser) return;
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      onLevel && onLevel(data);
      raf = requestAnimationFrame(tick);
    }

    function teardownMedia() {
      cancelAnimationFrame(raf);
      try { tapNode && tapNode.disconnect(); } catch { /* already gone */ }
      tapNode = null;
      if (stream) stream.getTracks().forEach((t) => t.stop());
      stream = null;
      if (actx) actx.close().catch(() => {});
      actx = null;
      analyser = null;
    }

    function teardownWs() {
      clearTimeout(resultTimer);
      if (ws) {
        try { ws.onmessage = ws.onerror = ws.onclose = null; ws.close(); } catch { /* gone */ }
        ws = null;
      }
    }

    async function startUpload() {
      mode = "upload";
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      actx = new (window.AudioContext || window.webkitAudioContext)();
      const src = actx.createMediaStreamSource(stream);
      analyser = actx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      parts = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
      recorder.onstop = async () => {
        teardownMedia();
        live = false;
        try {
          const wav = await to16kWav(new Blob(parts, { type: recorder.mimeType || "audio/webm" }));
          onDone && onDone(wav);
        } catch (err) {
          onError && onError(err);
        }
      };
      recorder.start();
      live = true;
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) tick();
    }

    async function startStream(url) {
      mode = "stream";
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      actx = new (window.AudioContext || window.webkitAudioContext)();
      if (!actx.audioWorklet || !actx.audioWorklet.addModule) throw new Error("no worklet");
      const src = actx.createMediaStreamSource(stream);
      analyser = actx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      await actx.audioWorklet.addModule(tapModuleUrl());
      tapNode = new AudioWorkletNode(actx, "remo-tap");
      src.connect(tapNode);
      ws = new WebSocket(url);
      gotResult = false;
      await new Promise((resolve, reject) => {
        ws.onopen = resolve;
        ws.onerror = () => reject(new Error("live loop unreachable"));
      });
      tapNode.port.onmessage = (e) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
      };
      ws.onmessage = (e) => {
        let msg = null;
        try { msg = JSON.parse(e.data); } catch { return; }
        if (!msg || typeof msg !== "object") return;
        if (msg.type === "partial" && msg.text) onPartial && onPartial(msg.text);
        else if (msg.type === "result") {
          gotResult = true;
          live = false;
          teardownMedia();
          teardownWs();
          onResult && onResult(msg);
        } else if (msg.type === "error") {
          live = false;
          teardownMedia();
          teardownWs();
          onError && onError(new Error(msg.message || "live loop failed"));
        }
      };
      ws.onclose = () => {
        if (!gotResult && live) {
          live = false;
          teardownMedia();
          teardownWs();
          onError && onError(new Error("live loop dropped"));
        }
      };
      live = true;
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) tick();
    }

    async function start(streamUrl) {
      if (streamUrl && window.WebSocket) {
        try {
          await startStream(streamUrl);
          return;
        } catch (err) {
          // Mic denials surface identically from the fallback; anything else
          // (no worklet, no socket) just means this browser streams nothing.
          teardownMedia();
          teardownWs();
        }
      }
      await startUpload();
    }

    function stop() {
      if (mode === "stream") {
        if (tapNode) { try { tapNode.disconnect(); } catch { /* gone */ } tapNode = null; }
        if (stream) stream.getTracks().forEach((t) => t.stop());
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "end" }));
          resultTimer = setTimeout(() => {
            if (!gotResult) {
              live = false;
              teardownMedia();
              teardownWs();
              onError && onError(new Error("live loop timed out"));
            }
          }, 20000);
        } else {
          live = false;
          teardownMedia();
          teardownWs();
          onError && onError(new Error("live loop dropped"));
        }
        return;
      }
      if (recorder && recorder.state !== "inactive") recorder.stop();
      else {
        live = false;
        cancelAnimationFrame(raf);
      }
    }

    function isLive() { return live; }

    return { start, stop, isLive };
  }

  return { createSession };
})();
