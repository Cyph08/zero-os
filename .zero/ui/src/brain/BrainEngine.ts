// Zero OS — Brain renderer.
// WebGL (three.js) node field on #bgl behind a 2D HUD overlay on #gc (sword, AI CORE,
// headers, boxed labels, corners). Imperative; React mounts it via BrainCanvas.
import * as THREE from 'three';
import {
  AGENTS, LSIDE, RSIDE, NF, brainRadius, hueFor, hslToRgb, hexRgb,
  type Persona, type Emotion,
} from './agents';

interface BNode {
  ox: number; oy: number; col: [number, number, number]; hue: number;
  id: string; side: 0 | 1; size: number; bright: number; out: number;
  ph: number; sp: number; amp: number;
}

const NODE_VS = `
attribute float aSize; attribute float aBright; attribute vec3 aColor;
uniform float uDpr; varying vec3 vColor; varying float vBright;
void main(){
  vColor = aColor; vBright = aBright;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uDpr;
}`;

const NODE_FS = `
precision mediump float;
varying vec3 vColor; varying float vBright;
void main(){
  vec2 d = gl_PointCoord - vec2(0.5);
  float r = length(d) * 2.0;
  if (r > 1.0) discard;
  float glow = pow(1.0 - r, 2.4);
  float core = smoothstep(0.42, 0.0, r);
  vec3 col = vColor * vBright + vec3(core) * 0.55;
  float a = clamp(glow * vBright * 1.4 + core * 0.9, 0.0, 1.0);
  gl_FragColor = vec4(col, a);
}`;

export class BrainEngine {
  private bgl: HTMLCanvasElement;
  private gc: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private persona: Persona;

  private W = 0; private H = 0; private DPR = 1;
  private NX = 0; private NY = 0; private BRX = 0; private BRY = 0;

  private nodes: BNode[] = [];
  private edges: [number, number][] = [];
  private centroids: Record<string, { x: number; y: number }> = {};
  private builtW = 0;

  private renderer!: THREE.WebGLRenderer;
  private scene!: THREE.Scene;
  private camera!: THREE.OrthographicCamera;
  private points!: THREE.Points;
  private lines!: THREE.LineSegments;
  private posArr!: Float32Array;
  private sizeArr!: Float32Array;
  private brightArr!: Float32Array;
  private lpos!: Float32Array;
  private lcol!: Float32Array;
  private glReady = false;

  private t = 0;
  private audioLevel = 0;
  private realAudio = 0;
  private emotion: Emotion = 'idle';
  private active: Record<string, boolean> = {};
  private raf = 0;

  constructor(bgl: HTMLCanvasElement, gc: HTMLCanvasElement, persona: Persona) {
    this.bgl = bgl; this.gc = gc; this.persona = persona;
    this.ctx = gc.getContext('2d')!;
    this.initGL();
    this.resize();
    this.loop = this.loop.bind(this);
  }

  // ── public API ───────────────────────────────────────────────────────────
  setActiveAgents(ids: string[]) {
    this.active = {};
    ids.forEach((id) => { this.active[id] = true; });
  }
  setEmotion(e: Emotion) { this.emotion = e; }
  setAudioLevel(level: number) { this.realAudio = Math.max(0, Math.min(1, level)); }
  setPersona(p: Persona) { this.persona = p; }
  start() { if (!this.raf) this.raf = requestAnimationFrame(this.loop); }
  stop() { if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; }
  dispose() {
    this.stop();
    try {
      this.points?.geometry.dispose();
      (this.points?.material as THREE.Material)?.dispose();
      this.lines?.geometry.dispose();
      (this.lines?.material as THREE.Material)?.dispose();
      this.renderer?.dispose();
    } catch { /* ignore */ }
  }

  // ── sizing ───────────────────────────────────────────────────────────────
  resize() {
    this.DPR = window.devicePixelRatio || 1;
    this.W = window.innerWidth;
    this.H = window.innerHeight;
    this.NX = NF.x * this.W;
    this.NY = NF.y * this.H;

    this.gc.width = this.W * this.DPR;
    this.gc.height = this.H * this.DPR;
    this.gc.style.width = this.W + 'px';
    this.gc.style.height = this.H + 'px';
    this.ctx.setTransform(this.DPR, 0, 0, this.DPR, 0, 0);

    if (this.glReady) {
      this.renderer.setPixelRatio(this.DPR);
      this.renderer.setSize(this.W, this.H, false);
      this.camera.left = 0; this.camera.right = this.W;
      this.camera.top = 0; this.camera.bottom = this.H;
      this.camera.updateProjectionMatrix();
      if (this.points) {
        const mat = this.points.material as THREE.ShaderMaterial;
        if (mat.uniforms) mat.uniforms.uDpr.value = this.DPR;
      }
    }
    this.buildBrain();
  }

  // ── brain geometry (leaf/wing lobes, side-graded hue) ──────────────────────
  private buildBrain() {
    const { RX, RY, GAP } = brainRadius(this.W, this.H);
    this.BRX = RX; this.BRY = RY;
    this.nodes = []; this.edges = []; this.centroids = {};

    const PER = 235;
    for (let side = 0 as 0 | 1; side < 2; side = (side + 1) as 0 | 1) {
      const sign = side === 0 ? -1 : 1;
      let accepted = 0, guard = 0;
      while (accepted < PER && guard < PER * 40) {
        guard++;
        const ax = GAP + Math.random() * (RX - GAP);
        const u = (ax - GAP) / (RX - GAP);               // 0 inner .. 1 outer
        const env = Math.sqrt(Math.max(0, 1 - u * u));   // half-ellipse (flat inner edge)
        const y = (Math.random() * 2 - 1) * RY * env;
        const x = sign * ax;
        accepted++;
        const v = (y / RY + 1) / 2;                       // 0 top .. 1 bottom
        const band = Math.max(0, Math.min(5, Math.floor(v * 6)));
        const ag = (side === 0 ? LSIDE : RSIDE)[band] || AGENTS[0];
        const prox = 1 - u;
        const hub = Math.random() < 0.15;
        const hue = hueFor(side, v) + (Math.random() * 16 - 8);
        const col = hslToRgb(hue, 0.92, hub ? 0.74 : 0.62);
        this.nodes.push({
          ox: x, oy: y, col, hue, id: ag.id, side,
          size: hub ? 7 + Math.random() * 5 : 3.2 + Math.random() * 2.3,
          bright: 0.5 + prox * 0.45 + (hub ? 0.3 : 0), out: 1 - prox,
          ph: Math.random() * 6.283, sp: 0.22 + Math.random() * 0.5, amp: 0.8 + Math.random() * 1.6,
        });
      }
    }

    // side-locked nearest-neighbour triangulated edges
    const thr2 = (RX * 0.17) * (RX * 0.17);
    for (let p = 0; p < this.nodes.length; p++) {
      const A = this.nodes[p];
      let cnt = 0;
      for (let q = p + 1; q < this.nodes.length && cnt < 6; q++) {
        const B = this.nodes[q];
        if (A.side !== B.side) continue;
        const dx = A.ox - B.ox, dy = A.oy - B.oy;
        if (dx * dx + dy * dy < thr2) { this.edges.push([p, q]); cnt++; }
      }
    }

    // per-agent centroids for label leaders
    const acc: Record<string, { x: number; y: number; n: number }> = {};
    for (const N of this.nodes) {
      (acc[N.id] ||= { x: 0, y: 0, n: 0 });
      acc[N.id].x += N.ox; acc[N.id].y += N.oy; acc[N.id].n++;
    }
    for (const k in acc) this.centroids[k] = { x: acc[k].x / acc[k].n, y: acc[k].y / acc[k].n };

    this.builtW = this.W;
    if (this.glReady) this.buildGLBuffers();
  }

  // ── three.js setup ─────────────────────────────────────────────────────────
  private initGL() {
    this.renderer = new THREE.WebGLRenderer({ canvas: this.bgl, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setClearColor(0x000000, 1);
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(0, this.W || 1, 0, this.H || 1, -1000, 1000);
    this.camera.position.z = 10;
    this.glReady = true;
  }

  private buildGLBuffers() {
    const N = this.nodes.length;
    if (this.points) { this.scene.remove(this.points); this.points.geometry.dispose(); (this.points.material as THREE.Material).dispose(); }
    if (this.lines) { this.scene.remove(this.lines); this.lines.geometry.dispose(); (this.lines.material as THREE.Material).dispose(); }

    this.posArr = new Float32Array(N * 3);
    this.sizeArr = new Float32Array(N);
    this.brightArr = new Float32Array(N);
    const colArr = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const n = this.nodes[i];
      this.sizeArr[i] = n.size;
      this.brightArr[i] = n.bright;
      colArr[i * 3] = n.col[0]; colArr[i * 3 + 1] = n.col[1]; colArr[i * 3 + 2] = n.col[2];
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute('position', new THREE.BufferAttribute(this.posArr, 3));
    pg.setAttribute('aSize', new THREE.BufferAttribute(this.sizeArr, 1));
    pg.setAttribute('aBright', new THREE.BufferAttribute(this.brightArr, 1));
    pg.setAttribute('aColor', new THREE.BufferAttribute(colArr, 3));
    const pm = new THREE.ShaderMaterial({
      vertexShader: NODE_VS, fragmentShader: NODE_FS,
      uniforms: { uDpr: { value: this.DPR } },
      transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(pg, pm);
    this.scene.add(this.points);

    const E = this.edges.length;
    this.lpos = new Float32Array(E * 6);
    this.lcol = new Float32Array(E * 6);
    for (let e = 0; e < E; e++) {
      const [a, b] = this.edges[e];
      const ca = this.nodes[a].col, cb = this.nodes[b].col;
      this.lcol[e * 6] = ca[0] * 0.45; this.lcol[e * 6 + 1] = ca[1] * 0.45; this.lcol[e * 6 + 2] = ca[2] * 0.45;
      this.lcol[e * 6 + 3] = cb[0] * 0.45; this.lcol[e * 6 + 4] = cb[1] * 0.45; this.lcol[e * 6 + 5] = cb[2] * 0.45;
    }
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.BufferAttribute(this.lpos, 3));
    lg.setAttribute('color', new THREE.BufferAttribute(this.lcol, 3));
    const lm = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending });
    this.lines = new THREE.LineSegments(lg, lm);
    this.scene.add(this.lines);
  }

  // ── per-frame ──────────────────────────────────────────────────────────────
  private loop() {
    this.frame();
    this.raf = requestAnimationFrame(this.loop);
  }

  private frame() {
    if (this.builtW !== this.W || !this.nodes.length) this.buildBrain();

    // emotion / audio drive the central energy
    let target = this.emotion === 'speaking'
      ? 0.5 + 0.5 * Math.abs(Math.sin(this.t * 7) + 0.4 * Math.sin(this.t * 11.3))
      : this.emotion === 'thinking' ? 0.55
      : this.emotion === 'listening' ? 0.32 : 0.12;
    if (this.realAudio > 0.001) target = this.realAudio;
    this.audioLevel += (target - this.audioLevel) * 0.18;

    // CPU drift -> shared buffers
    const N = this.nodes.length;
    const dx: number[] = new Array(N), dy: number[] = new Array(N);
    for (let i = 0; i < N; i++) {
      const n = this.nodes[i];
      const x = this.NX + n.ox + Math.cos(this.t * n.sp + n.ph) * n.amp;
      const y = this.NY + n.oy + Math.sin(this.t * n.sp * 1.2 + n.ph) * n.amp;
      dx[i] = x; dy[i] = y;
      this.posArr[i * 3] = x; this.posArr[i * 3 + 1] = y; this.posArr[i * 3 + 2] = 0;
      const on = this.active[n.id];
      this.brightArr[i] = on ? Math.min(1.4, n.bright + 0.6) : n.bright;
      this.sizeArr[i] = on ? n.size * 1.6 : n.size;
    }
    const pg = this.points.geometry;
    (pg.getAttribute('position') as THREE.BufferAttribute).needsUpdate = true;
    (pg.getAttribute('aBright') as THREE.BufferAttribute).needsUpdate = true;
    (pg.getAttribute('aSize') as THREE.BufferAttribute).needsUpdate = true;

    for (let e = 0; e < this.edges.length; e++) {
      const [a, b] = this.edges[e];
      const on = this.active[this.nodes[a].id] || this.active[this.nodes[b].id];
      const k = on ? 1.4 : 1;
      this.lpos[e * 6] = dx[a]; this.lpos[e * 6 + 1] = dy[a]; this.lpos[e * 6 + 2] = 0;
      this.lpos[e * 6 + 3] = dx[b]; this.lpos[e * 6 + 4] = dy[b]; this.lpos[e * 6 + 5] = 0;
      const ca = this.nodes[a].col, cb = this.nodes[b].col;
      this.lcol[e * 6] = ca[0] * 0.45 * k; this.lcol[e * 6 + 1] = ca[1] * 0.45 * k; this.lcol[e * 6 + 2] = ca[2] * 0.45 * k;
      this.lcol[e * 6 + 3] = cb[0] * 0.45 * k; this.lcol[e * 6 + 4] = cb[1] * 0.45 * k; this.lcol[e * 6 + 5] = cb[2] * 0.45 * k;
    }
    const lg = this.lines.geometry;
    (lg.getAttribute('position') as THREE.BufferAttribute).needsUpdate = true;
    (lg.getAttribute('color') as THREE.BufferAttribute).needsUpdate = true;

    this.renderer.render(this.scene, this.camera);

    // 2D overlay
    this.ctx.clearRect(0, 0, this.W, this.H);
    this.drawSword();
    this.drawHUD();
    this.drawLabels();

    this.t += 0.016;
  }

  // ── the SWORD — exact Markdown 4 shape (thin tapered beam + central bloom) ──
  private drawSword() {
    const c = this.ctx, cx = this.NX, cy = this.NY, BR = this.BRY || this.H * 0.3;
    const bodyH = BR * 1.04, top = cy - bodyH, bot = cy + bodyH;
    const w = 1 + this.audioLevel * 1.4;
    c.save(); c.globalCompositeOperation = 'lighter';

    // (1) thin violet glow column (uniform thin width, full length)
    const glowW = 4.5 * w;
    const gg = c.createLinearGradient(cx - glowW, 0, cx + glowW, 0);
    gg.addColorStop(0, 'rgba(140,70,220,0)'); gg.addColorStop(0.5, 'rgba(168,108,238,0.62)'); gg.addColorStop(1, 'rgba(140,70,220,0)');
    c.fillStyle = gg; c.fillRect(cx - glowW, top, glowW * 2, bodyH * 2);

    // (2) thin white-hot core
    const coreW = 1.5 + this.audioLevel * 1.5;
    const cg = c.createLinearGradient(cx - coreW, 0, cx + coreW, 0);
    cg.addColorStop(0, 'rgba(255,255,255,0)'); cg.addColorStop(0.5, 'rgba(255,255,255,0.96)'); cg.addColorStop(1, 'rgba(255,255,255,0)');
    c.fillStyle = cg; c.fillRect(cx - coreW, top, coreW * 2, bodyH * 2);

    // (3) ONE bright bloom (lens flare) at the centre = brightest point
    const bloomR = BR * 0.2 * (1 + this.audioLevel * 0.35);
    const bl = c.createRadialGradient(cx, cy, 0, cx, cy, bloomR);
    bl.addColorStop(0, 'rgba(255,255,255,0.92)'); bl.addColorStop(0.16, 'rgba(224,190,255,0.62)');
    bl.addColorStop(0.5, 'rgba(150,82,226,0.2)'); bl.addColorStop(1, 'rgba(140,70,220,0)');
    c.fillStyle = bl; c.beginPath(); c.arc(cx, cy, bloomR, 0, 6.283); c.fill();

    // (4) faint horizontal lens-flare streak across the bloom
    const fl = BR * 0.42;
    const fg = c.createLinearGradient(cx - fl, cy, cx + fl, cy);
    fg.addColorStop(0, 'rgba(196,158,255,0)'); fg.addColorStop(0.5, 'rgba(232,212,255,0.42)'); fg.addColorStop(1, 'rgba(196,158,255,0)');
    c.fillStyle = fg; c.fillRect(cx - fl, cy - 1.1, fl * 2, 2.2);

    // (5) taper the very ends to soft points
    c.globalCompositeOperation = 'destination-out';
    const fade = c.createLinearGradient(0, top, 0, bot);
    fade.addColorStop(0, 'rgba(0,0,0,1)'); fade.addColorStop(0.09, 'rgba(0,0,0,0)');
    fade.addColorStop(0.91, 'rgba(0,0,0,0)'); fade.addColorStop(1, 'rgba(0,0,0,1)');
    c.fillStyle = fade; c.fillRect(cx - glowW * 2, top, glowW * 4, bodyH * 2);
    c.restore();
  }

  // ── HUD text: AI CORE (centre ref), hemisphere headers, corner status ──────
  private drawHUD() {
    const c = this.ctx, cx = this.NX, cy = this.NY, W = this.W, H = this.H;
    const pc = this.persona.color;

    c.textAlign = 'center';
    c.fillStyle = 'rgba(200,214,238,0.66)'; c.font = '10px "Share Tech Mono",monospace';
    c.fillText('AI CORE', cx, cy - 20);
    c.fillStyle = 'rgba(150,175,205,0.45)'; c.font = '7px "Share Tech Mono",monospace';
    c.fillText(AGENTS.length + ' AGENTS', cx, cy + 20);
    c.fillText('1 SYSTEM', cx, cy + 30);

    c.textAlign = 'left';
    c.fillStyle = 'rgba(170,195,220,0.82)'; c.font = 'bold 11px "Share Tech Mono",monospace';
    c.fillText('LOGIC HEMISPHERE', 40, 52);
    c.fillStyle = 'rgba(120,150,180,0.55)'; c.font = '7px "Share Tech Mono",monospace';
    c.fillText('ANALYSE   STRUCTURE   OPTIMISE', 40, 64);
    c.textAlign = 'right';
    c.fillStyle = 'rgba(170,195,220,0.82)'; c.font = 'bold 11px "Share Tech Mono",monospace';
    c.fillText('CREATIVE HEMISPHERE', W - 40, 52);
    c.fillStyle = 'rgba(120,150,180,0.55)'; c.font = '7px "Share Tech Mono",monospace';
    c.fillText('IMAGINE   CONNECT   INNOVATE', W - 40, 64);

    const [pr, pg, pb] = hexRgb(pc);
    const pcol = (a: number) => `rgba(${pr},${pg},${pb},${a})`;
    c.textAlign = 'left';
    c.fillStyle = 'rgba(150,180,205,0.55)'; c.font = '9px "Share Tech Mono",monospace';
    c.fillText('SYSTEM STATUS', 40, H - 56);
    c.fillStyle = pcol(0.7);
    const st = this.emotion === 'speaking' ? 'SPEAKING' : this.emotion === 'thinking' ? 'THINKING' : this.emotion === 'listening' ? 'LISTENING' : 'ONLINE';
    c.fillText('● ' + st, 40, H - 43);
    c.textAlign = 'right';
    c.fillStyle = 'rgba(150,180,205,0.55)'; c.fillText('PERFORMANCE', W - 40, H - 56);
    c.fillStyle = pcol(0.7); c.fillText(AGENTS.length + ' AGENTS · DEEPSEEK', W - 40, H - 43);
    c.textAlign = 'left';
  }

  // ── boxed agent labels with short leaders to the lobe edge ─────────────────
  private drawLabels() {
    const c = this.ctx, W = this.W, NX = this.NX, NY = this.NY, BRX = this.BRX, BRY = this.BRY;
    const left = AGENTS.filter((a) => (this.centroids[a.id]?.x ?? 0) < 0).sort((p, q) => this.centroids[p.id].y - this.centroids[q.id].y);
    const right = AGENTS.filter((a) => (this.centroids[a.id]?.x ?? 0) >= 0).sort((p, q) => this.centroids[p.id].y - this.centroids[q.id].y);
    const boxW = Math.round(W * 0.092), boxH = 26, gapFromLobe = Math.round(W * 0.045);
    const topY = NY - BRY * 0.82, botY = NY + BRY * 0.82;

    const drawCol = (list: typeof AGENTS, lft: boolean) => {
      const n = list.length;
      for (let k = 0; k < n; k++) {
        const ag = list[k], on = !!this.active[ag.id];
        const slotY = Math.round(n > 1 ? topY + k * (botY - topY) / (n - 1) : NY);
        const boxInnerX = NX + (lft ? -1 : 1) * (BRX + gapFromLobe);
        const boxLeft = lft ? boxInnerX - boxW : boxInnerX;
        const dy = Math.max(-1, Math.min(1, (slotY - NY) / BRY));
        const edgeX = NX + (lft ? -1 : 1) * BRX * Math.sqrt(Math.max(0, 1 - dy * dy));
        const [r, g, b] = hexRgb(ag.color);
        const rgba = (a: number) => `rgba(${r},${g},${b},${a})`;
        c.strokeStyle = rgba(on ? 0.85 : 0.3); c.lineWidth = on ? 1.3 : 0.7;
        c.beginPath(); c.moveTo(boxInnerX, slotY); c.lineTo(edgeX, slotY); c.stroke();
        c.fillStyle = ag.color; c.fillRect(boxInnerX - 2.5, slotY - 2.5, 5, 5);
        c.strokeStyle = rgba(on ? 0.9 : 0.34); c.lineWidth = on ? 1.2 : 0.8;
        if (on) { c.fillStyle = rgba(0.06); c.fillRect(boxLeft, slotY - boxH / 2, boxW, boxH); }
        c.strokeRect(boxLeft, slotY - boxH / 2, boxW, boxH);
        const tx = boxLeft + 9;
        c.textAlign = 'left';
        c.fillStyle = on ? '#ffffff' : rgba(0.96); c.font = 'bold 11px "Share Tech Mono",monospace';
        c.fillText(ag.name, tx, slotY - 1);
        c.fillStyle = on ? rgba(0.95) : 'rgba(150,175,205,0.6)'; c.font = '7px "Share Tech Mono",monospace';
        c.fillText(ag.fn.toUpperCase(), tx, slotY + 9);
      }
    };
    drawCol(left, true); drawCol(right, false);
    c.textAlign = 'left';
  }
}
