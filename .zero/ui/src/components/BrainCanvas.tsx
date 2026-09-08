import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { BrainEngine } from '../brain/BrainEngine';
import type { Emotion, Persona } from '../brain/agents';

export interface BrainHandle {
  setActiveAgents: (ids: string[]) => void;
  setEmotion: (e: Emotion) => void;
  setAudioLevel: (l: number) => void;
  setPersona: (p: Persona) => void;
}

interface Props { persona: Persona; }

const BrainCanvas = forwardRef<BrainHandle, Props>(({ persona }, ref) => {
  const bglRef = useRef<HTMLCanvasElement>(null);
  const gcRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<BrainEngine | null>(null);

  useEffect(() => {
    if (!bglRef.current || !gcRef.current) return;
    const engine = new BrainEngine(bglRef.current, gcRef.current, persona);
    engineRef.current = engine;
    engine.start();
    const onResize = () => engine.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      engine.dispose();
      engineRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { engineRef.current?.setPersona(persona); }, [persona]);

  useImperativeHandle(ref, () => ({
    setActiveAgents: (ids) => engineRef.current?.setActiveAgents(ids),
    setEmotion: (e) => engineRef.current?.setEmotion(e),
    setAudioLevel: (l) => engineRef.current?.setAudioLevel(l),
    setPersona: (p) => engineRef.current?.setPersona(p),
  }));

  return (
    <>
      <canvas ref={bglRef} className="layer" />
      <canvas ref={gcRef} className="layer" />
    </>
  );
});

BrainCanvas.displayName = 'BrainCanvas';
export default BrainCanvas;
