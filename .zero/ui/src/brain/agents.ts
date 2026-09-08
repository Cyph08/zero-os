// Zero OS — agent roster, persona palette, hue grading & brain geometry.
// Ported from the v6.2 zero.js so the visual design carries over unchanged.

export interface Agent {
  id: string;
  name: string;
  fn: string;
  color: string;
}

// 12 department agents. LEFT lobe = first 6 (Logic), RIGHT lobe = last 6 (Creative).
export const AGENTS: Agent[] = [
  { id: 'research',   name: 'Iris',    fn: 'Deep Research', color: '#00e5ff' },
  { id: 'career',     name: 'Maven',   fn: 'Career',        color: '#ff6b35' },
  { id: 'schedule',   name: 'Chrono',  fn: 'Scheduler',     color: '#b39ddb' },
  { id: 'brainstorm', name: 'Spark',   fn: 'Brainstorm',    color: '#ffeb3b' },
  { id: 'code',       name: 'Forge',   fn: 'Code',          color: '#69f0ae' },
  { id: 'study',      name: 'Sage',    fn: 'Study',         color: '#80deea' },
  { id: 'bci',        name: 'Synapse', fn: 'BCI / EEG',     color: '#ce93d8' },
  { id: 'health',     name: 'Pulse',   fn: 'Health',        color: '#f48fb1' },
  { id: 'comms',      name: 'Echo',    fn: 'Comms',         color: '#fff176' },
  { id: 'photo',      name: 'Lens',    fn: 'Photo Lab',     color: '#a5d6a7' },
  { id: 'news',       name: 'Herald',  fn: 'News',          color: '#ef9a9a' },
  { id: 'linkedin',   name: 'Nexus',   fn: 'Network',       color: '#90caf9' },
];

export const LSIDE = AGENTS.slice(0, 6);
export const RSIDE = AGENTS.slice(6, 12);

export interface Persona {
  name: string;
  color: string;
  placeholder: string;
}

export const PERSONAS: Record<string, Persona> = {
  zero: { name: 'Zero', color: '#00e5ff', placeholder: 'Ask Zero...' },
  v:    { name: 'V',    color: '#c792ea', placeholder: 'Ask V...' },
};

// Brain placement: centre of the page.
export const NF = { x: 0.5, y: 0.5 };

// Brain radius for a given viewport (contained vertical-oval, ~0.38 x 0.71).
export function brainRadius(w: number, h: number) {
  const R = Math.min(w * 0.19, h * 0.355, 400);
  return { RX: R, RY: R * 1.05, GAP: 18 };
}

// Piecewise hue gradient by side; v = vertical position 0 (top) -> 1 (bottom).
// LEFT keeps a green/teal low band (Cyph's choice); RIGHT magenta->pink->red->orange->yellow.
const L_STOPS: [number, number][] = [[0, 222], [0.4, 192], [0.7, 158], [1, 134]];
const R_STOPS: [number, number][] = [[0, 305], [0.28, 322], [0.52, 352], [0.74, 18], [1, 58]];

export function hueFor(side: 0 | 1, v: number): number {
  const st = side === 0 ? L_STOPS : R_STOPS;
  for (let i = 0; i < st.length - 1; i++) {
    if (v <= st[i + 1][0]) {
      const [t0, h0] = st[i];
      const [t1, h1] = st[i + 1];
      const f = (v - t0) / (t1 - t0 || 1);
      return h0 + (h1 - h0) * f;
    }
  }
  return st[st.length - 1][1];
}

export function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  h = (((h % 360) + 360) % 360) / 360;
  if (s === 0) return [l, l, l];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const hk = (t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [hk(h + 1 / 3), hk(h), hk(h - 1 / 3)];
}

export function hexRgb(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

export type Emotion = 'idle' | 'listening' | 'thinking' | 'speaking';
