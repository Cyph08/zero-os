import { useEffect, useState } from 'react';

interface Props { text: string; color: string; }

// Cyberpunk-style subtitle that streams the latest spoken line, then fades.
export default function Subtitle({ text, color }: Props) {
  const [shown, setShown] = useState('');
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!text) return;
    setShown('');
    setVisible(true);
    let i = 0;
    const id = setInterval(() => {
      i += 2;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(id);
    }, 16);
    const fade = setTimeout(() => setVisible(false), 6000 + text.length * 20);
    return () => { clearInterval(id); clearTimeout(fade); };
  }, [text]);

  return (
    <div className="subtitle" style={{ opacity: visible ? 1 : 0, color }}>
      {shown}
      {visible && <span className="caret" style={{ background: color }} />}
    </div>
  );
}
