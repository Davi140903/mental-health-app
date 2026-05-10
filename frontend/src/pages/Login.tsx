import { useState } from 'react';
import axios from 'axios';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';

function buildCodeMessage(debugCode: string | null, fallback: string) {
  if (!debugCode) {
    return `${fallback} Confira sua caixa de entrada.`;
  }
  return `${fallback} Neste ambiente local, use o codigo ${debugCode}.`;
}

function getApiErrorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
  }
  return fallback;
}

export default function Login() {
  const { login, requestLoginCode } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state ?? {}) as { email?: string; info?: string };
  const [email, setEmail] = useState(state.email ?? '');
  const [password, setPassword] = useState('');
  const [codigo, setCodigo] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState(state.info ?? '');
  const [codeRequested, setCodeRequested] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleRequestCode = async () => {
    setError('');
    setInfo('');

    if (!email.trim() || !password.trim()) {
      setError('Informe email e senha antes de pedir o codigo.');
      return;
    }

    setSendingCode(true);
    try {
      const response = await requestLoginCode(email, password);
      setCodeRequested(true);
      if (response.debug_code) {
        setCodigo(response.debug_code);
      }
      setInfo(buildCodeMessage(response.debug_code, 'Codigo de login enviado.'));
    } catch (error) {
      setError(getApiErrorMessage(error, 'Nao foi possivel enviar o codigo. Confira se o email existe e se a senha esta correta.'));
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');

    if (!codeRequested) {
      setError('Primeiro solicite o codigo de verificacao.');
      return;
    }

    if (codigo.trim().length !== 6) {
      setError('Informe o codigo de 6 digitos para entrar.');
      return;
    }

    setSubmitting(true);
    try {
      await login(email, password, codigo);
      navigate('/dashboard');
    } catch (error) {
      setError(getApiErrorMessage(error, 'Nao foi possivel entrar. Confira email, senha e codigo.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Mental Health App</h1>
        <p className="auth-subtitle">Entre com email, senha e codigo de verificacao.</p>

        {error ? <div className="alert error">{error}</div> : null}
        {info ? <div className="alert success">{info}</div> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Email</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>

          <label className="field">
            <span>Senha</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          <button
            type="button"
            className="secondary-button"
            onClick={() => void handleRequestCode()}
            disabled={sendingCode}
          >
            {sendingCode ? 'Enviando codigo...' : 'Pedir codigo por email'}
          </button>

          {codeRequested ? (
            <label className="field">
              <span>Codigo de verificacao</span>
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={codigo}
                onChange={(event) => setCodigo(event.target.value.replace(/\D/g, ''))}
                placeholder="Codigo preenchido automaticamente no modo local"
                required
              />
            </label>
          ) : null}

          <button type="submit" disabled={submitting}>
            {submitting ? 'Entrando...' : 'Entrar'}
          </button>
        </form>

        <p className="auth-footer">
          Ainda nao tem conta? <Link to="/register">Criar conta</Link>
        </p>
        <p className="auth-footer">
          Esqueceu a senha? <Link to="/recover">Recuperar acesso</Link>
        </p>
      </div>
    </div>
  );
}
