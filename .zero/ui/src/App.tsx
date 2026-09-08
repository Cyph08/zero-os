import { useEffect, useRef, useState } from 'react';
import BrainCanvas, { type BrainHandle } from './components/BrainCanvas';
import InputBar from './components/InputBar';
import Subtitle from './components/Subtitle';
import { PERSONAS, type Persona } from './brain/agents';
import { ask, replyText, tts, getPersona, switchPersona, health } from './api';

// quick keyword -> agent guess for instant visual feedback (ported from zero.js)
const KW: [string[], string][] = [
  [['research', 'find', 'search', 'look up', 'what is', 'who is'], 'research'],
  [['code', 'debug', 'function', 'python', 'error', 'bug', 'script'], 'code'],
  [['study', 'explain', 'learn', 'understand', 'concept', 'course'], 'study'],
  [['email', 'message', 'write to', 'contact', 'comms', 'draft'], 'comms'],
  [['schedule', 'calendar', 'remind', 'meeting', 'task', 'plan'], 'schedule'],
  [['health', 'gym', 'sleep', 'water', 'workout', 'exercise'], 'health'],
  [['news', 'headline', 'today', 'latest'], 'news'],
  [['bci', 'eeg', 'motor imagery', 'brain', 'neural', 'electrode'], 'bci'],
  [['photo', 'image', 'picture', 'nikon', 'camera', 'jpeg'], 'photo'],
  [['career', 'job', 'cv', 'resume', 'apply', 'work'], 'career'],
  [['idea', 'brainstorm', 'startup', 'mvp'], 'brainstorm'],
  [['linkedin', 'network', 'connect', 'profile', 'recruiter'], 'linkedin'],
];

function guessAgent(q: string): string | null {
  const s = q.toLowerCase();
  for (const [keys, id] of KW) if (keys.some((k) => s.includes(k))) return id;
  return null;
}

export default function App() {
  const brain = useRef<BrainHandle>(null);
  const [persona, setPersona] = useState<Persona>(PERSONAS.zero);
  const [online, setOnline] = useState(false);
  const [subtitle, setSubtitle] = useState('');

  // health poll
  useEffect(() => {
    let stop = false;
    const ping = async () => { if (!stop) setOnline(await health()); };
    ping();
    const id = setInterval(ping, 15000);
    return () => { stop = true; clearInterval(id); };
  }, []);

  // sync persona from server
  useEffect(() => {
    getPersona().then((p) => {
      if (p) setPersona({ name: p.name, color: p.color, placeholder: p.placeholder || `Ask ${p.name}...` });
    });
  }, []);

  const speak = async (text: string) => {
    try {
      const buf = await tts(text, persona.name.toLowerCase());
      const ac = new (window.AudioContext || (window as any).webkitAudioContext)();
      const ab = await ac.decodeAudioData(buf);
      const src = ac.createBufferSource(); src.buffer = ab;
      const an = ac.createAnalyser(); an.fftSize = 256;
      src.connect(an); an.connect(ac.destination); src.start(0);
      const data = new Uint8Array(an.frequencyBinCount);
      const sample = () => {
        an.getByteFrequencyData(data);
        let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i];
        brain.current?.setAudioLevel(Math.min(1, sum / data.length / 120));
        if (src.buffer && (ac.currentTime < (src as any)._end)) requestAnimationFrame(sample);
      };
      (src as any)._end = ac.currentTime + ab.duration;
      brain.current?.setEmotion('speaking');
      requestAnimationFrame(sample);
      src.onended = () => { brain.current?.setAudioLevel(0); brain.current?.setEmotion('idle'); };
    } catch { brain.current?.setEmotion('idle'); }
  };

  const onSend = async (q: string) => {
    brain.current?.setEmotion('thinking');
    const guess = guessAgent(q);
    if (guess) brain.current?.setActiveAgents([guess]);
    setSubtitle('...');
    try {
      const d = await ask(q);
      if (d.persona_switched && d.persona) {
        const p = { name: d.persona.name, color: d.persona.color, placeholder: d.persona.placeholder || `Ask ${d.persona.name}...` };
        setPersona(p);
      }
      const used = d.agents_used && d.agents_used.length ? d.agents_used : (guess ? [guess] : []);
      brain.current?.setActiveAgents(used);
      const reply = replyText(d) || JSON.stringify(d);
      setSubtitle(reply.slice(0, 320));
      await speak(reply.slice(0, 280));
      setTimeout(() => brain.current?.setActiveAgents([]), 2500);
    } catch {
      brain.current?.setEmotion('idle');
      brain.current?.setActiveAgents([]);
      setSubtitle('OFFLINE — start the backend on :8000');
    }
  };

  const togglePersona = async () => {
    const next = persona.name.toLowerCase() === 'v' ? 'zero' : 'v';
    const r = await switchPersona(next).catch(() => null);
    if (r?.persona) {
      setPersona({ name: r.persona.name, color: r.persona.color, placeholder: r.persona.placeholder || `Ask ${r.persona.name}...` });
    } else {
      setPersona(PERSONAS[next]); // optimistic if server offline
    }
  };

  return (
    <div className="app">
      <BrainCanvas ref={brain} persona={persona} />
      <button className="persona-chip" onClick={togglePersona} style={{ color: persona.color, borderColor: `${persona.color}66` }}>
        {persona.name.toUpperCase()}
      </button>
      <Subtitle text={subtitle} color={persona.color} />
      <InputBar placeholder={persona.placeholder} color={persona.color} online={online} onSend={onSend} />
    </div>
  );
}
