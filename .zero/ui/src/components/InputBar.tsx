import { useState } from 'react';

interface Props {
  placeholder: string;
  color: string;
  online: boolean;
  onSend: (text: string) => void;
}

export default function InputBar({ placeholder, color, online, onSend }: Props) {
  const [value, setValue] = useState('');
  const submit = () => {
    const q = value.trim();
    if (!q) return;
    setValue('');
    onSend(q);
  };
  return (
    <div className="inputbar">
      <span className="dot" style={{ background: online ? '#69f0ae' : '#ff5252' }} />
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
        style={{ borderColor: `${color}55` }}
        autoComplete="off"
        spellCheck={false}
      />
      <button onClick={submit} style={{ color, borderColor: `${color}55` }}>▶</button>
    </div>
  );
}
