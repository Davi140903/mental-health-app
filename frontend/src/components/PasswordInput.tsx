import { useState } from 'react';

interface PasswordInputProps {
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  minLength?: number;
  placeholder?: string;
}

export default function PasswordInput({ value, onChange, required, minLength, placeholder }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="password-input-wrap">
      <input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        minLength={minLength}
        required={required}
        placeholder={placeholder}
      />
      <button
        type="button"
        className="password-toggle"
        onClick={() => setVisible((current) => !current)}
        aria-label={visible ? 'Ocultar senha' : 'Mostrar senha'}
        title={visible ? 'Ocultar senha' : 'Mostrar senha'}
      >
        {visible ? (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3.3 2.2 2.2 3.3l4 4C4.7 8.4 3.5 10 2.5 12c2 4 5.2 6 9.5 6 1.4 0 2.6-.2 3.7-.6l5 5 1.1-1.1L3.3 2.2Zm8.7 14.2c-3.4 0-5.9-1.5-7.7-4.4.8-1.4 1.8-2.6 3-3.5l2 2A3.2 3.2 0 0 0 12 15.2c.5 0 .9-.1 1.3-.3l1.2 1.2c-.8.2-1.6.3-2.5.3Zm.4-2.7H12a1.7 1.7 0 0 1-1.7-1.7v-.4l2.1 2.1ZM12 6c4.3 0 7.5 2 9.5 6a11.7 11.7 0 0 1-2.7 3.5l-1.1-1.1c.8-.6 1.5-1.4 2-2.4-1.8-2.9-4.3-4.4-7.7-4.4-.8 0-1.5.1-2.2.3L8.6 6.7c1-.5 2.1-.7 3.4-.7Zm3.2 6c0 .3 0 .6-.1.8l-3.9-3.9c.3-.1.5-.1.8-.1a3.2 3.2 0 0 1 3.2 3.2Z" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 6c4.3 0 7.5 2 9.5 6-2 4-5.2 6-9.5 6s-7.5-2-9.5-6C4.5 8 7.7 6 12 6Zm0 10.4c3.4 0 5.9-1.5 7.7-4.4-1.8-2.9-4.3-4.4-7.7-4.4S6.1 9.1 4.3 12c1.8 2.9 4.3 4.4 7.7 4.4Zm0-1.2a3.2 3.2 0 1 1 0-6.4 3.2 3.2 0 0 1 0 6.4Zm0-1.5a1.7 1.7 0 1 0 0-3.4 1.7 1.7 0 0 0 0 3.4Z" />
          </svg>
        )}
      </button>
    </div>
  );
}
