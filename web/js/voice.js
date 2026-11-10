/* Voice capture: mic -> 16kHz mono WAV + live level meter. No mock audio. */
window.RemoVoice = (() => {
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

  function createSession({ onLevel, onDone, onError }) {
    let stream = null, recorder = null, actx = null, analyser = null, raf = 0;
    let parts = [];
    let live = false;

    function tick() {
      if (!live || !analyser) return;
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      onLevel && onLevel(data);
      raf = requestAnimationFrame(tick);
    }

    async function start() {
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
        cancelAnimationFrame(raf);
        stream.getTracks().forEach((t) => t.stop());
        actx.close().catch(() => {});
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

    function stop() {
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
