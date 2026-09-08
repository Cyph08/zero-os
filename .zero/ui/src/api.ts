// Backend (FastAPI) at :8000. Endpoint shapes match the existing server.
const API = 'http://localhost:8000';

export interface AskResult {
  response?: string; result?: string; explanation?: string; summary?: string; error?: string;
  agents_used?: string[];
  persona_switched?: boolean;
  persona?: { name: string; color: string; placeholder?: string };
  model_used?: string;
  duration_ms?: number;
}

export async function ask(input: string): Promise<AskResult> {
  const r = await fetch(`${API}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input }),
  });
  return r.json();
}

export function replyText(d: AskResult): string {
  return d.response || d.result || d.explanation || d.summary || d.error || '';
}

export async function tts(text: string, persona: string): Promise<ArrayBuffer> {
  const r = await fetch(`${API}/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, persona }),
  });
  if (!r.ok) throw new Error('TTS ' + r.status);
  return r.arrayBuffer();
}

export async function getPersona(): Promise<{ name: string; color: string; placeholder?: string } | null> {
  try { return await (await fetch(`${API}/persona/current`)).json(); } catch { return null; }
}

export async function switchPersona(name: string) {
  const r = await fetch(`${API}/persona/switch/${name}`, { method: 'POST' });
  return r.json();
}

export async function health(): Promise<boolean> {
  try {
    const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(2500) });
    return r.ok;
  } catch { return false; }
}
