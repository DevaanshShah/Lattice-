/* ============================================================
   Lattice — cinematic 3D laptop intro
   Self-contained ES module. No build step, no framework.
   Loads Three.js from CDN at runtime; fails gracefully.
   Exposes window.playLatticeIntro() and respects:
     - prefers-reduced-motion  → skip
     - sessionStorage lt_intro_seen (once per tab)
     - ?intro query param      → force replay
   ============================================================ */

const SEEN_KEY = 'lt_intro_seen';
const THREE_URL = 'https://unpkg.com/three@0.160.0/build/three.module.js';

const AMBER = '#F2B441';
const INK   = '#ECEAE3';
const BG    = '#0E0E12';

const HEAD_FONT = '"Bricolage Grotesque", "Avenir Next", "Segoe UI", sans-serif';
const BODY_FONT = '"Geist", "Inter", "Helvetica Neue", sans-serif';

/* ---------- overlay helpers ---------- */

function overlayEl() { return document.getElementById('intro-root'); }

function ensureOverlay() {
  let root = overlayEl();
  if (!root) {
    root = document.createElement('div');
    root.id = 'intro-root';
    document.body.appendChild(root);
  }
  root.style.position = 'fixed';
  root.style.inset = '0';
  root.style.zIndex = '9999';
  if (!root.style.background) {
    root.style.background =
      'radial-gradient(120% 90% at 50% 38%, #17171d 0%, #0E0E12 55%, #08080b 100%)';
  }
  return root;
}

function removeOverlay(fade) {
  const root = overlayEl();
  if (!root) return;
  if (!fade) { root.remove(); return; }
  root.style.transition = 'opacity .45s ease';
  root.style.pointerEvents = 'none';
  root.style.opacity = '0';
  setTimeout(() => root.remove(), 500);
}

/* ---------- easings (hand-rolled, no GSAP) ---------- */

const clamp01 = (v) => Math.max(0, Math.min(1, v));
const lerp = (a, b, t) => a + (b - a) * t;
const easeOutCubic  = (t) => 1 - Math.pow(1 - t, 3);
const easeInCubic   = (t) => t * t * t;
const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOutBack = (t) => { const c = 1.70158, c3 = c + 1; return 1 + c3 * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); };

/* ---------- 2D canvas helpers (textures) ---------- */

function makeCanvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  return c;
}

function rr(ctx, x, y, w, h, r) {
  const rad = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.arcTo(x + w, y, x + w, y + h, rad);
  ctx.arcTo(x + w, y + h, x, y + h, rad);
  ctx.arcTo(x, y + h, x, y, rad);
  ctx.arcTo(x, y, x + w, y, rad);
  ctx.closePath();
}

function drawScreen(ctx, w, h) {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, w, h);

  // faint top glow
  const glow = ctx.createRadialGradient(w / 2, -80, 40, w / 2, -80, 560);
  glow.addColorStop(0, 'rgba(242,180,65,0.12)');
  glow.addColorStop(1, 'rgba(242,180,65,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  // nav
  ctx.fillStyle = AMBER;
  rr(ctx, 56, 34, 36, 36, 9); ctx.fill();
  ctx.fillStyle = '#141008';
  ctx.font = `700 22px ${HEAD_FONT}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('L', 74, 53);
  ctx.fillStyle = INK;
  ctx.textAlign = 'left';
  ctx.font = `600 26px ${HEAD_FONT}`;
  ctx.fillText('Lattice', 104, 53);
  ctx.font = `500 15px ${BODY_FONT}`;
  ctx.fillStyle = 'rgba(236,234,227,0.55)';
  ctx.textAlign = 'right';
  ctx.fillText('Gallery      Pricing      Docs', w - 60, 53);
  ctx.strokeStyle = 'rgba(236,234,227,0.08)';
  ctx.beginPath(); ctx.moveTo(0, 86); ctx.lineTo(w, 86); ctx.stroke();

  // headline
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = INK;
  ctx.font = `600 52px ${HEAD_FONT}`;
  ctx.fillText('Turn any idea into', w / 2, 208);
  ctx.fillStyle = AMBER;
  ctx.fillText('an explainer video.', w / 2, 268);
  ctx.fillStyle = 'rgba(236,234,227,0.6)';
  ctx.font = `400 18px ${BODY_FONT}`;
  ctx.fillText('Type a prompt. Lattice writes, narrates, and animates it.', w / 2, 312);

  // prompt pill
  const pw = 640, ph = 64, px = (w - pw) / 2, py = 348;
  ctx.fillStyle = '#17171E';
  rr(ctx, px, py, pw, ph, 32); ctx.fill();
  ctx.strokeStyle = 'rgba(242,180,65,0.4)'; ctx.lineWidth = 1.5;
  rr(ctx, px, py, pw, ph, 32); ctx.stroke();
  ctx.fillStyle = 'rgba(236,234,227,0.45)';
  ctx.font = `400 17px ${BODY_FONT}`;
  ctx.textAlign = 'left';
  ctx.fillText('a 90-second explainer on mycelium networks…', px + 28, py + 39);
  // generate button
  const bw = 150, bh = 44;
  ctx.fillStyle = AMBER;
  rr(ctx, px + pw - bw - 10, py + 10, bw, bh, 22); ctx.fill();
  ctx.fillStyle = '#141008';
  ctx.font = `600 16px ${BODY_FONT}`;
  ctx.textAlign = 'center';
  ctx.fillText('Generate ▸', px + pw - bw / 2 - 10, py + 38);

  // thumbnail cards
  const cw = 272, ch = 140, gap = 24;
  const total = cw * 3 + gap * 2;
  let cx = (w - total) / 2;
  const cy = 452;
  const tints = ['rgba(242,180,65,0.20)', 'rgba(127,168,255,0.16)', 'rgba(236,234,227,0.10)'];
  const labels = ['How rockets land themselves', 'Why sourdough is alive', 'CRISPR in 90 seconds'];
  for (let i = 0; i < 3; i++) {
    ctx.fillStyle = '#15151B';
    rr(ctx, cx, cy, cw, ch, 14); ctx.fill();
    const g = ctx.createLinearGradient(cx, cy, cx + cw, cy + ch);
    g.addColorStop(0, tints[i]);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    rr(ctx, cx, cy, cw, ch, 14); ctx.fill();
    ctx.strokeStyle = 'rgba(236,234,227,0.08)';
    rr(ctx, cx, cy, cw, ch, 14); ctx.stroke();
    // play button
    ctx.fillStyle = 'rgba(242,180,65,0.92)';
    ctx.beginPath(); ctx.arc(cx + cw / 2, cy + 56, 19, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#141008';
    ctx.beginPath();
    ctx.moveTo(cx + cw / 2 - 5, cy + 47);
    ctx.lineTo(cx + cw / 2 + 8, cy + 56);
    ctx.lineTo(cx + cw / 2 - 5, cy + 65);
    ctx.closePath(); ctx.fill();
    // caption
    ctx.fillStyle = 'rgba(236,234,227,0.7)';
    ctx.font = `500 13px ${BODY_FONT}`;
    ctx.textAlign = 'center';
    ctx.fillText(labels[i], cx + cw / 2, cy + ch - 18);
    cx += cw + gap;
  }
}

function drawKeyboard(ctx, w, h) {
  ctx.fillStyle = '#1A1A20';
  ctx.fillRect(0, 0, w, h);
  const rows = 5, cols = 14;
  const kx0 = 60, ky0 = 40, kw = (w - 120) / cols, kh = 54, gap = 8;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      // spacebar row
      if (r === 4 && c >= 4 && c <= 9) {
        if (c === 4) {
          ctx.fillStyle = '#232329';
          rr(ctx, kx0 + 4 * kw + 3, ky0 + 4 * (kh + gap), kw * 6 - 6, kh, 8);
          ctx.fill();
        }
        continue;
      }
      ctx.fillStyle = (r === 0 && c === cols - 1) ? 'rgba(242,180,65,0.7)' : '#232329';
      rr(ctx, kx0 + c * kw + 3, ky0 + r * (kh + gap), kw - 6, kh, 8);
      ctx.fill();
    }
  }
  // trackpad
  ctx.fillStyle = '#202027';
  rr(ctx, w / 2 - 160, ky0 + 5 * (kh + gap) + 14, 320, h - (ky0 + 5 * (kh + gap)) - 44, 14);
  ctx.fill();
}

function glowCanvas(size, color) {
  const c = makeCanvas(size, size);
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, color);
  g.addColorStop(0.35, color.replace(/[\d.]+\)$/, '0.28)'));
  g.addColorStop(1, color.replace(/[\d.]+\)$/, '0)'));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return c;
}

/* ---------- DOM chrome (skip button + mascot) ---------- */

function buildChrome(root, onSkip) {
  const style = document.createElement('style');
  style.textContent = `
    #intro-root .lt-skip {
      position:absolute; top:22px; right:24px; z-index:3;
      background:transparent; cursor:pointer;
      border:1px solid rgba(236,234,227,.25); border-radius:999px;
      color:rgba(236,234,227,.7); padding:8px 18px;
      font:500 13px ${BODY_FONT}; letter-spacing:.05em;
      transition:color .2s, border-color .2s, background .2s;
    }
    #intro-root .lt-skip:hover {
      color:${AMBER}; border-color:${AMBER}; background:rgba(242,180,65,.08);
    }
    #intro-root .lt-mascot {
      position:absolute; left:26px; bottom:26px; z-index:3;
      display:flex; align-items:flex-end; gap:12px;
      opacity:0; transform:translateY(18px);
      transition:opacity .45s ease, transform .45s cubic-bezier(.2,1.4,.4,1);
      pointer-events:none;
    }
    #intro-root .lt-mascot.on { opacity:1; transform:none; }
    #intro-root .lt-bot {
      font-size:42px; line-height:1;
      filter:drop-shadow(0 6px 14px rgba(0,0,0,.5));
      animation:lt-bot-bob 2.4s ease-in-out infinite;
    }
    #intro-root .lt-bubble {
      background:#1B1B22; color:${INK};
      border:1px solid rgba(242,180,65,.35);
      border-radius:14px 14px 14px 4px;
      padding:10px 14px; max-width:250px; margin-bottom:8px;
      font:500 15.5px/1.4 ${BODY_FONT};
      transform-origin:0 100%;
    }
    #intro-root .lt-bubble.pop { animation:lt-pop .32s cubic-bezier(.2,1.5,.4,1); }
    @keyframes lt-pop { from { transform:scale(.6); opacity:0; } to { transform:scale(1); opacity:1; } }
    @keyframes lt-bot-bob { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-5px); } }
  `;
  root.appendChild(style);

  const skip = document.createElement('button');
  skip.className = 'lt-skip';
  skip.type = 'button';
  skip.textContent = 'Skip intro';
  skip.addEventListener('click', onSkip);
  root.appendChild(skip);

  const mascot = document.createElement('div');
  mascot.className = 'lt-mascot';
  mascot.innerHTML = '<div class="lt-bubble"></div>';
  root.appendChild(mascot);

  return { style, skip, mascot, bubble: mascot.querySelector('.lt-bubble') };
}

/* ---------- the intro itself ---------- */

async function runIntro(THREE, root) {
  return new Promise((resolve) => {
    let done = false;
    let raf = 0;

    const canvas = document.createElement('canvas');
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;';
    root.appendChild(canvas);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 120);
    const camHome = new THREE.Vector3(0, 2.05, 7.4);
    const lookHome = new THREE.Vector3(0, 0.65, 0);
    camera.position.copy(camHome);
    camera.lookAt(lookHome);

    function resize() {
      const w = root.clientWidth || window.innerWidth;
      const h = root.clientHeight || window.innerHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    resize();
    window.addEventListener('resize', resize);

    /* lights: ambient + key directional + warm amber point + cool rim */
    scene.add(new THREE.AmbientLight(0xffffff, 0.4));
    const key = new THREE.DirectionalLight(0xfff1dd, 1.6);
    key.position.set(4, 7, 5);
    scene.add(key);
    const amberPt = new THREE.PointLight(0xF2B441, 14, 24, 1.6);
    amberPt.position.set(-4.2, 2.2, 3.2);
    scene.add(amberPt);
    const rim = new THREE.DirectionalLight(0x7fa8ff, 1.1);
    rim.position.set(-3, 4.5, -6);
    scene.add(rim);

    /* textures */
    const screenCv = makeCanvas(1024, 640);
    drawScreen(screenCv.getContext('2d'), 1024, 640);
    const screenTex = new THREE.CanvasTexture(screenCv);
    screenTex.colorSpace = THREE.SRGBColorSpace;

    const kbCv = makeCanvas(1024, 680);
    drawKeyboard(kbCv.getContext('2d'), 1024, 680);
    const kbTex = new THREE.CanvasTexture(kbCv);
    kbTex.colorSpace = THREE.SRGBColorSpace;

    // redraw once webfonts arrive
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => {
        if (done) return;
        drawScreen(screenCv.getContext('2d'), 1024, 640);
        drawKeyboard(kbCv.getContext('2d'), 1024, 680);
        screenTex.needsUpdate = true;
        kbTex.needsUpdate = true;
      }).catch(() => {});
    }

    /* laptop */
    const laptop = new THREE.Group();
    scene.add(laptop);

    const alu = new THREE.MeshStandardMaterial({ color: 0x2b2b33, metalness: 0.75, roughness: 0.38 });
    const aluDark = new THREE.MeshStandardMaterial({ color: 0x1e1e25, metalness: 0.7, roughness: 0.45 });

    const base = new THREE.Mesh(new THREE.BoxGeometry(3, 0.12, 2), alu);
    base.position.y = 0.06;
    laptop.add(base);

    const kb = new THREE.Mesh(
      new THREE.PlaneGeometry(2.84, 1.88),
      new THREE.MeshStandardMaterial({ map: kbTex, metalness: 0.2, roughness: 0.85 })
    );
    kb.rotation.x = -Math.PI / 2;
    kb.position.y = 0.121;
    laptop.add(kb);

    // lid group hinged at the back edge
    const lid = new THREE.Group();
    lid.position.set(0, 0.12, -1);
    laptop.add(lid);

    const lidShell = new THREE.Mesh(new THREE.BoxGeometry(3, 0.08, 2), aluDark);
    lidShell.position.set(0, 0.04, 1);
    lid.add(lidShell);

    // amber logo on lid top (visible while closed/tumbling)
    const logoCv = makeCanvas(128, 128);
    const lctx = logoCv.getContext('2d');
    lctx.fillStyle = AMBER;
    rr(lctx, 14, 14, 100, 100, 26); lctx.fill();
    lctx.fillStyle = '#141008';
    lctx.font = `700 64px ${HEAD_FONT}`;
    lctx.textAlign = 'center'; lctx.textBaseline = 'middle';
    lctx.fillText('L', 64, 68);
    const logoTex = new THREE.CanvasTexture(logoCv);
    logoTex.colorSpace = THREE.SRGBColorSpace;
    const logo = new THREE.Mesh(
      new THREE.PlaneGeometry(0.26, 0.26),
      new THREE.MeshBasicMaterial({ map: logoTex, transparent: true })
    );
    logo.rotation.x = -Math.PI / 2;
    logo.position.set(0, 0.081, 1);
    lid.add(logo);

    // screen plane on the lid's inner face
    const screenMat = new THREE.MeshBasicMaterial({ map: screenTex, side: THREE.DoubleSide, toneMapped: false });
    screenMat.color.setScalar(0); // powered off
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(2.8, 1.72), screenMat);
    screen.rotation.x = Math.PI / 2;
    screen.position.set(0, -0.006, 1.02);
    lid.add(screen);

    /* soft radial contact shadow */
    const shadowTex = new THREE.CanvasTexture(glowCanvas(256, 'rgba(0,0,0,0.55)'));
    const shadowMat = new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, opacity: 0, depthWrite: false });
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(4.6, 3.4), shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = -0.02;
    scene.add(shadow);

    /* amber bloom halo behind the screen */
    const haloTex = new THREE.CanvasTexture(glowCanvas(256, 'rgba(242,180,65,0.85)'));
    const haloMat = new THREE.SpriteMaterial({ map: haloTex, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
    const halo = new THREE.Sprite(haloMat);
    halo.scale.set(7.5, 5.6, 1);
    halo.position.set(0, 1, -1.6);
    scene.add(halo);

    /* chrome */
    const bubbles = [
      'yo, that\u2019s the actual site',
      'type an idea \u2192 get a video. wild.',
      'ok i\u2019m going in\u2014',
    ];
    const chrome = buildChrome(root, () => finish(true));

    /* cleanup */
    function finish(skipped) {
      if (done) return;
      done = true;
      cancelAnimationFrame(raf);
      clearTimeout(watchdog);
      window.removeEventListener('resize', resize);
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          if (o.material.map) o.material.map.dispose();
          o.material.dispose();
        }
      });
      renderer.dispose();
      removeOverlay(skipped); // skip = quick fade; timeline end already faded
      resolve();
    }

    // internal backstop: never trap the app
    const watchdog = setTimeout(() => finish(true), 15000);

    /* ---------- timeline (~7.5s) ---------- */
    const T = {
      fly:   [0.0, 2.1],   // fly in, closed, tumbling
      spin:  [2.1, 4.2],   // 360° Y-spin
      open:  [2.3, 4.05],  // lid opens w/ overshoot
      power: [4.05, 4.95], // screen powers on
      dive:  [6.35, 7.35], // camera dives into screen
      fade:  [7.0, 7.6],   // overlay crossfade
      end:   7.7,
    };
    const ph = (t, [a, b]) => clamp01((t - a) / (b - a));

    const mascotShowAt = 4.45;
    const bubbleTimes = [4.45, 5.35, 6.15];
    let bubbleIdx = -1;
    let mascotOn = false;

    const v0 = new THREE.Vector3();
    const v1 = new THREE.Vector3();
    const camStart = new THREE.Vector3();
    const lookCur = lookHome.clone();
    let diveLocked = false;

    let t = 0;
    let last = performance.now();

    function animate(now) {
      raf = requestAnimationFrame(animate);
      t += Math.min((now - last) / 1000, 0.05); // hidden-tab safe
      last = now;

      /* fly-in */
      const f = easeOutCubic(ph(t, T.fly));
      laptop.position.z = lerp(-26, 0, f);
      laptop.position.y = lerp(1.4, 0, f);
      const s = lerp(0.25, 1, f);
      laptop.scale.setScalar(s);
      laptop.rotation.x = lerp(1.1, 0.0, f);
      laptop.rotation.z = lerp(0.55, 0, f);
      const flyRy = lerp(-2.6, 0, f);

      /* 360° spin */
      const spin = easeInOutCubic(ph(t, T.spin));
      laptop.rotation.y = flyRy + spin * Math.PI * 2;

      /* lid open with overshoot */
      const open = easeOutBack(ph(t, T.open));
      lid.rotation.x = -1.85 * open;

      /* contact shadow fades in as it lands */
      shadowMat.opacity = clamp01((t - 1.7) / 0.7) * 0.75;
      shadow.scale.setScalar(lerp(0.5, 1, f));

      /* power on */
      const p = easeOutCubic(ph(t, T.power));
      screenMat.color.setScalar(p);
      haloMat.opacity = p * (0.55 + 0.3 * Math.sin(Math.min(p * Math.PI, Math.PI)));

      /* idle bob */
      if (t > T.spin[1]) {
        const it = t - T.spin[1];
        laptop.position.y = Math.sin(it * 1.7) * 0.045;
        laptop.rotation.x = Math.sin(it * 1.1) * 0.02;
      }

      /* mascot + bubbles */
      if (!mascotOn && t >= mascotShowAt) {
        mascotOn = true;
        chrome.mascot.classList.add('on');
      }
      const nextIdx = bubbleTimes.reduce((acc, bt, i) => (t >= bt ? i : acc), -1);
      if (nextIdx !== bubbleIdx && nextIdx >= 0) {
        bubbleIdx = nextIdx;
        chrome.bubble.textContent = bubbles[bubbleIdx];
        chrome.bubble.classList.remove('pop');
        void chrome.bubble.offsetWidth;
        chrome.bubble.classList.add('pop');
      }

      /* camera dive into the screen */
      const d = ph(t, T.dive);
      if (d > 0) {
        if (!diveLocked) {
          diveLocked = true;
          camStart.copy(camera.position);
          chrome.skip.style.opacity = '0';
          chrome.skip.style.pointerEvents = 'none';
        }
        const e = easeInCubic(d);
        screen.getWorldPosition(v0);           // screen center
        screen.getWorldDirection(v1);          // screen normal
        if (v1.dot(new THREE.Vector3().subVectors(camStart, v0)) < 0) v1.negate();
        const endPos = v0.clone().addScaledVector(v1, 0.34);
        camera.position.lerpVectors(camStart, endPos, e);
        lookCur.lerpVectors(lookHome, v0, clamp01(e * 1.7));
        camera.lookAt(lookCur);
        chrome.mascot.style.opacity = String(1 - e * 1.6);
      } else {
        camera.lookAt(lookHome);
      }

      /* crossfade overlay to reveal the app */
      const fd = ph(t, T.fade);
      if (fd > 0) {
        root.style.opacity = String(1 - fd);
        root.style.pointerEvents = 'none';
      }

      renderer.render(scene, camera);

      if (t >= T.end) finish(false);
    }
    raf = requestAnimationFrame(animate);
  });
}

/* ---------- entry ---------- */

async function playLatticeIntro(force = false) {
  const reduced = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const params = new URLSearchParams(window.location.search);
  const forced = force === true || params.has('intro');

  let seen = false;
  try { seen = sessionStorage.getItem(SEEN_KEY) === '1'; } catch (e) { /* private mode */ }

  if (reduced || (seen && !forced)) {
    removeOverlay(false);
    return;
  }
  try { sessionStorage.setItem(SEEN_KEY, '1'); } catch (e) { /* ok */ }

  const root = ensureOverlay();
  root.style.opacity = '1';
  root.style.pointerEvents = 'auto';

  let THREE;
  try {
    THREE = await import(/* @vite-ignore */ THREE_URL);
  } catch (err) {
    console.warn('[lattice-intro] Three.js failed to load — revealing app.', err);
    removeOverlay(false);
    return;
  }

  try {
    await runIntro(THREE, root);
  } catch (err) {
    console.warn('[lattice-intro] intro crashed — revealing app.', err);
    removeOverlay(false);
  }
}

window.playLatticeIntro = () => {
  // rebuild the cover if it was already removed, then force-play
  const root = ensureOverlay();
  root.style.opacity = '1';
  playLatticeIntro(true);
};

playLatticeIntro();
