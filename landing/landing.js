/* Remo landing motion: living hero with a playable studio turn, ambient life,
   and varied scroll choreography. GSAP + ScrollTrigger via CDN. Without them
   (offline) or under prefers-reduced-motion, tabs still work and all content
   stays visible: initial states come from JS only, never pre-hidden in CSS. */
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MOTION = !reduce && !!window.gsap;
  if (MOTION) gsap.registerPlugin(ScrollTrigger);

  /* ---------- studio demo data (copy identical to the page) ---------- */
  const SCENES = {
    save: {
      title: "Keyword Auto-Save",
      lang: "hi-IN, Prisma v2.5",
      badge: "SAVED",
      quote: "\u201cYaad rakhna, issue 214: login fix ho gaya, docs baaki hai.\u201d",
      reply: "Samajh gaya: 1 done, 1 baaki. Yaad kar liya.",
      chips: '<span class="chip-ok">\u2713 login fix</span><span class="chip-pend">\u25CB docs baaki</span>'
    },
    leftoff: {
      title: "Left-Off Recall",
      lang: "hi-IN, Timbre Avinash",
      badge: "RECALL",
      quote: "\u201cIssue 214 mein kya bacha hai?\u201d",
      reply: "Issue 214 mein 1 cheez baaki hai: docs. Login fix ho gaya tha.",
      chips: '<span class="chip-pend">\u25CB Pending first</span><span class="chip-ok">\u2713 Spoken reply</span>'
    },
    welcome: {
      title: "Welcome Back Briefing",
      lang: "Watcher, GitHub Delta",
      badge: "BRIEFING",
      quote: "\u201cWelcome back\u201d",
      reply: "Aapka 1 task baaki hai, aur python/cpython par 2 naye updates aaye hain.",
      chips: '<span class="chip-pend">\u25CB 1 pending</span><span class="chip-ok">\u2197 2 fresh deltas</span>'
    }
  };
  const ORDER = ["save", "leftoff", "welcome"];
  const $ = (id) => document.getElementById(id);
  const winTabs = Array.from(document.querySelectorAll(".win-tab"));
  const winWindow = document.querySelector(".stage-window");
  const playBtn = $("win-play");

  function paintScene(key) {
    const s = SCENES[key];
    if (!s) return;
    winTabs.forEach((b) => b.classList.toggle("active", b.dataset.scene === key));
    $("scene-title").textContent = s.title;
    $("scene-lang").textContent = s.lang;
    $("scene-badge").textContent = s.badge;
    $("scene-quote").textContent = s.quote;
    $("scene-reply").textContent = s.reply;
    $("scene-chips").innerHTML = s.chips;
    const time = document.querySelector(".win-time");
    if (time) time.textContent = "0:04";
  }

  /* ---------- showpiece: the studio performs a full voice turn ---------- */
  let sceneIdx = 0, playing = true, perfTl = null, heroVisible = true, perfGen = 0;
  let speakBoost = 1;

  function setPlaying(on) {
    playing = on;
    if (playBtn) {
      playBtn.setAttribute("aria-pressed", on ? "true" : "false");
      playBtn.setAttribute("aria-label", on ? "Pause the demo turn" : "Play the demo turn");
      playBtn.querySelector(".ic-pause").hidden = !on;
      playBtn.querySelector(".ic-play").hidden = on;
    }
    syncPerf();
  }

  function syncPerf() {
    if (!perfTl) return;
    if (playing && heroVisible && !document.hidden) perfTl.play();
    else perfTl.pause();
  }

  function performScene(key) {
    const s = SCENES[key];
    if (!s || !MOTION) { paintScene(key); return; }
    if (perfTl) perfTl.kill();
    const quoteEl = $("scene-quote"), replyEl = $("scene-reply"),
      chipsEl = $("scene-chips"), badgeEl = $("scene-badge"),
      timeEl = document.querySelector(".win-time");
    const words = s.reply.split(" ");
    const typeDur = Math.min(1.5, Math.max(0.8, s.quote.length * 0.028));
    const gen = ++perfGen;
    const tl = gsap.timeline({ onComplete: () => {
      if (!playing || gen !== perfGen) return;
      sceneIdx = (ORDER.indexOf(key) + 1) % ORDER.length;
      gsap.delayedCall(0.45, () => { if (playing && gen === perfGen) performScene(ORDER[sceneIdx]); });
    }});
    perfTl = tl;
    // Arm: tab lights, window nudges like a camera finding its subject.
    tl.call(() => {
      winTabs.forEach((b) => b.classList.toggle("active", b.dataset.scene === key));
      $("scene-title").textContent = s.title;
      $("scene-lang").textContent = s.lang;
      $("scene-badge").textContent = s.badge;
      quoteEl.textContent = "";
      replyEl.textContent = "";
      chipsEl.innerHTML = s.chips;
      gsap.set(chipsEl.children, { autoAlpha: 0, y: 8 });
      gsap.set(badgeEl, { scale: 0.7, autoAlpha: 0 });
      if (timeEl) timeEl.textContent = "0:00";
    }, null, 0);
    if (winWindow) tl.fromTo(winWindow, { y: 0 }, { y: -7, duration: 0.28, ease: "sine.out" }, 0)
      .to(winWindow, { y: 0, duration: 0.5, ease: "sine.inOut" }, 0.3);
    // Hear: the quote types itself (deterministic char tween, not an interval).
    const type = { i: 0 };
    tl.to(type, {
      i: s.quote.length, duration: typeDur, ease: "none",
      onUpdate: () => { quoteEl.textContent = s.quote.slice(0, Math.round(type.i)); }
    }, 0.3);
    // Think: reply dots pulse while the bars lean in.
    tl.call(() => { replyEl.textContent = "\u2022\u2022\u2022"; }, null, 1.95);
    tl.fromTo(replyEl, { opacity: 0.25 }, { opacity: 1, duration: 0.22, yoyo: true, repeat: 3 }, 1.95);
    tl.to({ b: 1 }, { b: 1.6, duration: 0.4, onUpdate: function () { speakBoost = this.targets()[0].b; } }, 1.95);
    // Speak: reply streams word by word, timer runs in sync.
    const stream = { i: 0 };
    tl.call(() => { replyEl.textContent = ""; }, null, 2.45);
    tl.to(stream, {
      i: words.length, duration: 2.0, ease: "none",
      onUpdate: () => { replyEl.textContent = words.slice(0, Math.round(stream.i)).join(" "); }
    }, 2.45);
    const clock = { v: 0 };
    tl.to(clock, {
      v: 4, duration: 2.0, ease: "none",
      onUpdate: () => { if (timeEl) timeEl.textContent = `0:0${Math.round(clock.v)}`; }
    }, 2.45);
    // Resolve: chips land one by one, badge pops, bars settle.
    tl.to(chipsEl.children[0], { autoAlpha: 1, y: 0, duration: 0.45, ease: "back.out(1.8)" }, 2.9);
    if (chipsEl.children[1]) tl.to(chipsEl.children[1], { autoAlpha: 1, y: 0, duration: 0.45, ease: "back.out(1.8)" }, 3.6);
    tl.to(badgeEl, { scale: 1, autoAlpha: 1, duration: 0.5, ease: "back.out(2)" }, 4.35);
    tl.to({ b: 1.6 }, { b: 1, duration: 0.6, onUpdate: function () { speakBoost = this.targets()[0].b; } }, 4.35);
    syncPerf();
  }

  winTabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = ORDER.indexOf(btn.dataset.scene);
      if (i < 0) return;
      sceneIdx = i;
      if (!MOTION || !playing) { paintScene(ORDER[sceneIdx]); return; }
      performScene(ORDER[sceneIdx]); // redirect the performance, keep it playing
    });
  });
  if (playBtn) {
    if (!MOTION) playBtn.style.display = "none";
    else playBtn.addEventListener("click", () => setPlaying(!playing));
  }
  if (!MOTION) return; // tabs above still work; everything below needs GSAP

  // Pause the showpiece off-screen or in hidden tabs.
  ScrollTrigger.create({
    trigger: ".hero", start: "top bottom", end: "bottom top",
    onToggle: (self) => { heroVisible = self.isActive; syncPerf(); }
  });
  document.addEventListener("visibilitychange", syncPerf);
  performScene(ORDER[sceneIdx]); // the show starts on load

  /* ---------- signature: waveforms that play themselves ---------- */
  const barGroups = [
    { nodes: Array.from(document.querySelectorAll(".win-bars i")), amp: 20 },
    { nodes: Array.from(document.querySelectorAll(".mini-wave i")), amp: 9 },
  ].filter((g) => g.nodes.length);
  const bases = new Map();
  barGroups.forEach((g) => g.nodes.forEach((n, i) => {
    bases.set(n, { base: parseFloat(n.style.height) || 50, i });
  }));
  gsap.ticker.add(() => {
    if (document.hidden || !heroVisible) return;
    const t = gsap.ticker.time; // deterministic: pure function of timeline time
    barGroups.forEach((g) => g.nodes.forEach((n) => {
      const { base, i } = bases.get(n);
      const wave = 0.62 * Math.sin(2.1 * t + i * 0.55) + 0.38 * Math.sin(3.7 * t + i * 1.31);
      const h = base + g.amp * speakBoost * wave;
      n.style.height = `${Math.max(8, Math.min(100, h)).toFixed(1)}%`;
    }));
  });

  /* ---------- load choreography ---------- */
  const loadTl = gsap.timeline({ defaults: { ease: "power4.out" } });
  loadTl.from(".topbar", { y: -18, autoAlpha: 0, duration: 0.7 }, 0);

  // Headline: masked line rolls with directional blur (built after fonts load).
  function splitHeadline() {
    const h1 = document.querySelector(".hero-copy h1");
    if (!h1 || h1.dataset.split) return;
    h1.dataset.split = "1";
    const parts = h1.innerHTML.split(/<br\s*\/?>/i);
    h1.innerHTML = parts.map((p) => `<span class="line"><span class="line-inner">${p}</span></span>`).join("");
  }
  document.fonts.ready.then(() => {
    splitHeadline();
    const inners = document.querySelectorAll(".hero-copy h1 .line-inner");
    if (!inners.length) return;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.style.position = "absolute";
    svg.innerHTML = `<filter id="mblur" x="-70%" y="-70%" width="240%" height="240%">
      <feGaussianBlur stdDeviation="0 14"/></filter>`;
    document.body.appendChild(svg);
    const blur = svg.querySelector("feGaussianBlur");
    inners.forEach((el) => { el.style.filter = "url(#mblur)"; });
    const o = { v: 14 };
    gsap.to(o, {
      v: 0, duration: 0.9, ease: "power4.out",
      onUpdate: () => blur.setAttribute("stdDeviation", `0 ${o.v.toFixed(1)}`),
      onComplete: () => inners.forEach((el) => { el.style.filter = "none"; })
    });
    gsap.from(inners, { yPercent: 112, duration: 0.9, stagger: 0.12, ease: "power4.out" });
  });

  loadTl.from(".hero-lead", { y: 26, autoAlpha: 0, duration: 0.8 }, 0.35)
    .from(".action-banner", { y: 26, autoAlpha: 0, duration: 0.8 }, 0.47)
    .from(".platforms", { y: 20, autoAlpha: 0, duration: 0.7 }, 0.58)
    .from(".stats-strip > div", { y: 18, autoAlpha: 0, duration: 0.6, stagger: 0.08 }, 0.66)
    .from(".stage-window", {
      y: 64, rotateY: -13, rotateX: 5, transformPerspective: 1200,
      autoAlpha: 0, duration: 1.15
    }, 0.4)
    .from(".ascii-signal", { autoAlpha: 0, duration: 1.2 }, 0.5);

  // Stats count up once (numeric dd only; "Zero" stays put).
  document.querySelectorAll(".stats-strip dd").forEach((dd) => {
    const m = dd.textContent.match(/^(\d+)\s*(.*)$/);
    if (!m) return;
    const target = parseInt(m[1], 10), suffix = m[2] ? ` ${m[2]}` : "";
    const o = { v: 0 };
    gsap.to(o, {
      v: target, duration: 1.4, delay: 0.7, ease: "power2.out",
      onUpdate: () => { dd.textContent = `${Math.round(o.v)}${suffix}`; }
    });
  });

  // Ambient background wash drift (slow gradient walk, 14 s loop).
  gsap.to(document.body, {
    backgroundPosition: "4% 3%, -3% 2%, 0% 0%",
    duration: 14, ease: "sine.inOut", yoyo: true, repeat: -1
  });
  gsap.to(".ascii-signal", { y: -10, opacity: 0.75, duration: 8, ease: "sine.inOut", yoyo: true, repeat: -1 });

  // Hero mouse parallax + magnetic CTAs (fine pointers only).
  if (window.matchMedia("(pointer: fine)").matches && winWindow) {
    const stage = document.querySelector(".hero-stage");
    const qx = gsap.quickTo(winWindow, "rotationY", { duration: 0.6 }),
      qy = gsap.quickTo(winWindow, "rotationX", { duration: 0.6 }),
      px = gsap.quickTo(winWindow, "x", { duration: 0.6 }),
      py = gsap.quickTo(winWindow, "y", { duration: 0.6 });
    gsap.set(winWindow, { transformPerspective: 1200 });
    document.querySelector(".hero").addEventListener("mousemove", (e) => {
      const r = stage.getBoundingClientRect();
      const nx = (e.clientX - (r.left + r.width / 2)) / r.width,
        ny = (e.clientY - (r.top + r.height / 2)) / r.height;
      qx(nx * 7); qy(-ny * 5); px(nx * 10); py(ny * 8);
    });
    document.querySelectorAll(".hero-copy .btn-primary, .hero-copy .btn-ghost, .banner-bar-actions .btn-primary").forEach((btn) => {
      const bx = gsap.quickTo(btn, "x", { duration: 0.3 }), by = gsap.quickTo(btn, "y", { duration: 0.3 });
      btn.addEventListener("mousemove", (e) => {
        const r = btn.getBoundingClientRect();
        bx((e.clientX - (r.left + r.width / 2)) * 0.18);
        by((e.clientY - (r.top + r.height / 2)) * 0.28);
      });
      btn.addEventListener("mouseleave", () => { bx(0); by(0); });
    });
  }

  // Topbar deepens + nav link follows the section in view.
  ScrollTrigger.create({
    start: 40, onUpdate: (self) => {
      document.querySelector(".topbar").classList.toggle("scrolled", self.scroll() > 40);
    }
  });
  gsap.to(".scroll-progress", {
    scaleX: 1, ease: "none",
    scrollTrigger: { trigger: document.body, start: "top top", end: "bottom bottom", scrub: 0.3 }
  });
  [["#workflows", "Workflows"], ["#how", "How it works"], ["#compare", "Why Remo"],
   ["#models", "Gnani AI"], ["#privacy", "Privacy"], ["#start", "Start"]].forEach(([id, label]) => {
    const link = Array.from(document.querySelectorAll(".nav-links a"))
      .find((a) => a.textContent.trim() === label);
    if (!link || !document.querySelector(id)) return;
    ScrollTrigger.create({
      trigger: id, start: "top 45%", end: "bottom 45%",
      onToggle: (self) => {
        if (self.isActive) {
          document.querySelectorAll(".nav-links a").forEach((a) => a.classList.remove("active"));
          link.classList.add("active");
        }
      }
    });
  });
  /* ---------- scroll choreography (varied per section, never uniform) ---------- */
  const once = { once: true, start: "top 85%" };
  // Banner image parallax (scale-first so no edge gaps) + caption cascade.
  gsap.fromTo(".hero-banner-frame img", { yPercent: -6, scale: 1.07 }, {
    yPercent: 6, scale: 1.07, ease: "none",
    scrollTrigger: { trigger: ".banner-hero", start: "top bottom", end: "bottom top", scrub: true }
  });
  gsap.from(".hero-banner-bar", {
    y: 30, autoAlpha: 0, duration: 0.9, ease: "power4.out",
    scrollTrigger: { trigger: ".banner-hero", start: "top 75%", once: true }
  });
  // Showcase: rising stagger, then each mini-window performs its moment.
  gsap.from(".bento-card", {
    y: 52, autoAlpha: 0, duration: 0.9, ease: "power4.out", stagger: 0.1,
    scrollTrigger: { trigger: ".bento", ...once }
  });
  document.querySelectorAll(".bento-card").forEach((card) => {
    ScrollTrigger.create({
      trigger: card, start: "top 78%", once: true,
      onEnter: () => {
        const tl = gsap.timeline();
        tl.fromTo(card.querySelectorAll(".m-tag"), { autoAlpha: 0.2 }, { autoAlpha: 1, duration: 0.3, repeat: 3, yoyo: true }, 0)
          .from(card.querySelectorAll(".m-line, .m-item, .mini-ack, .mini-pills"), {
            y: 12, autoAlpha: 0, duration: 0.55, ease: "power4.out", stagger: 0.09
          }, 0.15);
      }
    });
  });
  // How: steps slide in from the left, numbers flip, connector draws.
  gsap.from(".step-card", {
    x: -60, autoAlpha: 0, duration: 0.85, ease: "power4.out", stagger: 0.12,
    scrollTrigger: { trigger: ".steps-grid", ...once }
  });
  gsap.from(".step-n", {
    rotationX: -90, transformPerspective: 600, duration: 0.7, ease: "back.out(1.6)", stagger: 0.12,
    scrollTrigger: { trigger: ".steps-grid", ...once }
  });
  ScrollTrigger.create({
    trigger: ".steps-grid", start: "top 80%", once: true,
    onEnter: () => document.querySelector(".steps-grid").classList.add("draw")
  });
  // Try: table rows slide in from the right (alternating direction).
  gsap.from(".say-table tbody tr", {
    x: 60, autoAlpha: 0, duration: 0.7, ease: "power4.out", stagger: 0.07,
    scrollTrigger: { trigger: ".say-table", ...once }
  });
  // Compare: rows rise gently, then the Remo column takes a highlight sweep.
  gsap.from(".compare-table tbody tr", {
    y: 26, autoAlpha: 0, duration: 0.65, ease: "power4.out", stagger: 0.06,
    scrollTrigger: { trigger: ".compare-table", ...once }
  });
  ScrollTrigger.create({
    trigger: ".compare-table", start: "top 70%", once: true,
    onEnter: () => gsap.fromTo(".compare-table tbody td:nth-child(2)",
      { backgroundColor: "rgba(110,29,49,0.14)" },
      { backgroundColor: "rgba(110,29,49,0)", duration: 0.9, stagger: 0.12, delay: 0.4 })
  });
  // Models: cards rotate in from depth (the one 3D entrance) + tilt on hover.
  gsap.from("#models .info-card", {
    rotateY: -30, autoAlpha: 0, transformPerspective: 1000,
    duration: 0.9, ease: "power4.out", stagger: 0.12,
    scrollTrigger: { trigger: "#models .cards-3", ...once }
  });
  if (window.matchMedia("(pointer: fine)").matches) {
    document.querySelectorAll("#models .info-card").forEach((card) => {
      const rx = gsap.quickTo(card, "rotationX", { duration: 0.4 }),
        ry = gsap.quickTo(card, "rotationY", { duration: 0.4 });
      gsap.set(card, { transformPerspective: 900 });
      card.addEventListener("mousemove", (e) => {
        const r = card.getBoundingClientRect();
        ry(((e.clientX - r.left) / r.width - 0.5) * 10);
        rx(-((e.clientY - r.top) / r.height - 0.5) * 8);
      });
      card.addEventListener("mouseleave", () => { rx(0); ry(0); });
    });
  }
  // Pill marquee: slow infinite drift (static wrapping row without motion).
  (() => {
    const row = document.querySelector(".pill-row");
    if (!row || row.dataset.mq) return;
    row.dataset.mq = "1";
    row.classList.add("marquee");
    const track = document.createElement("div");
    track.className = "mq-track";
    track.append(...Array.from(row.children));
    const ghost = track.cloneNode(true);
    ghost.setAttribute("aria-hidden", "true");
    row.append(track, ghost);
    gsap.to(row.children, { xPercent: -100, duration: 22, ease: "none", repeat: -1 });
  })();
  // Privacy: rise, then the limits box wipes open.
  gsap.from("#privacy .info-card", {
    y: 44, autoAlpha: 0, duration: 0.85, ease: "power4.out", stagger: 0.1,
    scrollTrigger: { trigger: "#privacy .cards-3", ...once }
  });
  gsap.from(".limits-box", {
    clipPath: "inset(0 100% 0 0)", duration: 0.9, ease: "power4.inOut",
    scrollTrigger: { trigger: ".limits-box", ...once }
  });
  // Start: settle in, then the install commands type themselves.
  gsap.from(".closing-card", {
    y: 48, scale: 0.97, autoAlpha: 0, duration: 1, ease: "power4.out",
    scrollTrigger: { trigger: ".closing-card", ...once }
  });
  ScrollTrigger.create({
    trigger: ".code-box", start: "top 80%", once: true,
    onEnter: () => {
      const code = document.querySelector(".code-box code");
      if (!code || code.dataset.typed) return;
      code.dataset.typed = "1";
      const full = code.textContent;
      const o = { i: 0 };
      gsap.to(o, {
        i: full.length, duration: Math.min(4, full.length * 0.028), ease: "none",
        onUpdate: () => { code.textContent = full.slice(0, Math.round(o.i)); }
      });
    }
  });
  gsap.from(".footer-row", {
    y: 24, autoAlpha: 0, duration: 0.8, ease: "power4.out",
    scrollTrigger: { trigger: ".footer", ...once }
  });
})();
