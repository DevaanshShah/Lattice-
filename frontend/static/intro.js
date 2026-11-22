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

// Mirrors the LIVE Fourier landing (app.js landing()) so the camera dive
// lands seamlessly on the real page: left-aligned editorial hero + epicycle demo.
function drawScreen(ctx, w, h) {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, w, h);

  // faint lattice grid backdrop (like drawLattice on the real landing)
  ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(150,148,140,0.05)';
  for (let x = 0; x <= w; x += 44) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
  for (let y = 0; y <= h; y += 44) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  ctx.fillStyle = 'rgba(242,180,65,0.13)';
  for (let x = 0; x <= w; x += 44) for (let y = 0; y <= h; y += 44) { if ((x + y) % 132 === 0) ctx.fillRect(x - 1, y - 1, 2, 2); }
  const glow = ctx.createRadialGradient(w * 0.3, -70, 40, w * 0.3, -70, 520);
  glow.addColorStop(0, 'rgba(242,180,65,0.10)'); glow.addColorStop(1, 'rgba(242,180,65,0)');
  ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h);

  // ---- topbar (lattice glyph + wordmark + tabs) ----
  ctx.strokeStyle = AMBER; ctx.lineWidth = 1.5;
  rr(ctx, 40, 26, 26, 26, 4); ctx.stroke();
  ctx.strokeStyle = 'rgba(242,180,65,0.5)'; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(40 + 26 / 3, 26); ctx.lineTo(40 + 26 / 3, 52);
  ctx.moveTo(40 + 52 / 3, 26); ctx.lineTo(40 + 52 / 3, 52);
  ctx.moveTo(40, 26 + 26 / 3); ctx.lineTo(66, 26 + 26 / 3);
  ctx.moveTo(40, 26 + 52 / 3); ctx.lineTo(66, 26 + 52 / 3);
  ctx.stroke();
  ctx.fillStyle = INK; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  ctx.font = `600 20px ${HEAD_FONT}`; ctx.fillText('Lattice', 78, 40);
  ctx.font = `500 11px ${BODY_FONT}`; ctx.fillStyle = 'rgba(236,234,227,0.5)';
  ctx.textAlign = 'center';
  ['HOME', 'LEARN', 'TEACH', 'GALLERY'].forEach((s, i) => ctx.fillText(s, w / 2 - 132 + i * 88, 40));
  ctx.strokeStyle = 'rgba(236,234,227,0.08)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, 66); ctx.lineTo(w, 66); ctx.stroke();

  // ---- hero (left-aligned, matches the real landing) ----
  const lx = 56;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.strokeStyle = AMBER; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(lx, 118); ctx.lineTo(lx + 22, 118); ctx.stroke();
  ctx.fillStyle = 'rgba(236,234,227,0.55)'; ctx.font = `500 12px ${BODY_FONT}`;
  ctx.fillText('M A D E - T O - O R D E R   E X P L A I N E R S', lx + 32, 122);
  ctx.fillStyle = INK; ctx.font = `600 52px ${HEAD_FONT}`;
  ctx.fillText('Turn any idea into', lx, 188);
  ctx.fillText('an ', lx, 248);
  const anW = ctx.measureText('an ').width;
  ctx.fillStyle = AMBER; ctx.fillText('explainer video.', lx + anW, 248);
  ctx.fillStyle = 'rgba(236,234,227,0.55)'; ctx.font = `400 16px ${BODY_FONT}`;
  ctx.fillText('Describe a concept in a sentence. Lattice storyboards it,', lx, 292);
  ctx.fillText('animates every idea, and narrates the whole thing.', lx, 314);

  // input bar (bordered + amber "Create video →", like the real one)
  const iw = 468, ih = 52, iy = 344;
  ctx.fillStyle = '#16161B'; rr(ctx, lx, iy, iw, ih, 8); ctx.fill();
  ctx.strokeStyle = 'rgba(236,234,227,0.14)'; ctx.lineWidth = 1; rr(ctx, lx, iy, iw, ih, 8); ctx.stroke();
  ctx.fillStyle = 'rgba(236,234,227,0.4)'; ctx.font = `400 15px ${BODY_FONT}`;
  ctx.fillText('Explain how neural networks learn…', lx + 16, iy + 33);
  const bw = 150;
  ctx.fillStyle = AMBER; rr(ctx, lx + iw - bw, iy, bw, ih, 8); ctx.fill();
  ctx.fillStyle = '#141008'; ctx.font = `600 14px ${BODY_FONT}`; ctx.textAlign = 'center';
  ctx.fillText('Create video →', lx + iw - bw / 2, iy + 32);
  ctx.textAlign = 'left';
  ctx.fillStyle = 'rgba(236,234,227,0.3)'; ctx.font = `400 11px ${BODY_FONT}`;
  ctx.fillText('TRY    the Fourier series      how RSA works      eigenvectors', lx, iy + ih + 26);

  // ---- live-demo panel (epicycles → wave), the signature of the real landing ----
  const px = 556, py = 100, pw = w - px - 44, phh = 452;
  ctx.fillStyle = '#0B0B10'; rr(ctx, px, py, pw, phh, 10); ctx.fill();
  ctx.strokeStyle = 'rgba(236,234,227,0.10)'; ctx.lineWidth = 1; rr(ctx, px, py, pw, phh, 10); ctx.stroke();
  ctx.save();
  rr(ctx, px, py, pw, phh, 10); ctx.clip();
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  for (let x = px; x <= px + pw; x += 30) { ctx.beginPath(); ctx.moveTo(x, py); ctx.lineTo(x, py + phh); ctx.stroke(); }
  for (let y = py; y <= py + phh; y += 30) { ctx.beginPath(); ctx.moveTo(px, y); ctx.lineTo(px + pw, y); ctx.stroke(); }
  // header + label
  ctx.fillStyle = 'rgba(236,234,227,0.5)'; ctx.font = `500 10px ${BODY_FONT}`; ctx.textAlign = 'left';
  ctx.fillText('LIVE · FROM PROMPT TO PREVIEW', px + 16, py + 22);
  ctx.textAlign = 'right'; ctx.fillText('FOURIER SERIES', px + pw - 16, py + 22);
  // epicycle chain (static snapshot)
  const amp = phh * 0.19, cx = px + pw * 0.34, cy = py + phh * 0.52;
  const angs = [0.5, -1.35, 2.05, -0.65, 1.15];
  let ex = cx, ey = cy;
  for (let i = 0; i < 5; i++) {
    const n = 2 * i + 1, r = amp * (4 / (Math.PI * n)), a = angs[i];
    ctx.strokeStyle = 'rgba(236,234,227,0.14)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(ex, ey, r, 0, Math.PI * 2); ctx.stroke();
    const nx = ex + r * Math.cos(a), ny = ey + r * Math.sin(a);
    ctx.strokeStyle = AMBER; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(nx, ny); ctx.stroke();
    ctx.fillStyle = AMBER; ctx.beginPath(); ctx.arc(nx, ny, 2.6, 0, Math.PI * 2); ctx.fill();
    ex = nx; ey = ny;
  }
  // wave trailing to the right, glowing amber
  const waveX0 = cx + amp + 22;
  ctx.strokeStyle = 'rgba(236,234,227,0.28)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(waveX0, ey); ctx.stroke();
  ctx.strokeStyle = AMBER; ctx.lineWidth = 2.4; ctx.shadowColor = AMBER; ctx.shadowBlur = 10;
  ctx.beginPath();
  for (let i = 0; waveX0 + i * 1.6 < px + pw - 8; i++) {
    const wx = waveX0 + i * 1.6;
    if (i === 0) ctx.moveTo(wx, ey); else ctx.lineTo(wx, cy + Math.sin(i * 0.10) * amp * 0.55);
  }
  ctx.stroke(); ctx.shadowBlur = 0;
  ctx.restore();
  ctx.fillStyle = 'rgba(236,234,227,0.65)'; ctx.font = `500 11px ${BODY_FONT}`; ctx.textAlign = 'left';
  ctx.fillText('Scene 03 · Stacking the harmonics', px + 16, py + phh - 16);
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
