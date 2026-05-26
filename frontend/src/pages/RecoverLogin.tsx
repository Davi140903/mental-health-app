import { useState } from 'react';
import axios from 'axios';
import { Link, useNavigate } from 'react-router-dom';
import PasswordInput from '../components/PasswordInput';
import { useAuth } from '../contexts/useAuth';

function buildCodeMessage(debugCode: string | null, fallback: string) {
  if (!debugCode) {
    return `${fallback} Confira sua caixa de entrada.`;
  }
  return `${fallback} Neste ambiente local, use o código ${debugCode}.`;
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

export default function RecoverLogin() {
  const { requestPasswordResetCode, resetPassword } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [novaSenha, setNovaSenha] = useState('');
  const [confirmNovaSenha, setConfirmNovaSenha] = useState('');
  const [codigo, setCodigo] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [codeRequested, setCodeRequested] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const validatePassword = () => {
    if (novaSenha.length < 6) {
      return 'A nova senha precisa ter pelo menos 6 caracteres.';
    }
    if (novaSenha !== confirmNovaSenha) {
      return 'As senhas não coincidem.';
    }
    return '';
  };

  const handleRequestCode = async () => {
    setError('');
    setInfo('');

    if (!email.trim()) {
      setError('Informe o email da conta antes de pedir o código.');
      return;
    }

    setSendingCode(true);
    try {
      const response = await requestPasswordResetCode(email);
      setCodeRequested(true);
      if (response.debug_code) {
        setCodigo(response.debug_code);
      }
      setInfo(buildCodeMessage(response.debug_code, 'Código de recuperação enviado.'));
    } catch (error) {
      setError(getApiErrorMessage(error, 'Não foi possível enviar o código de recuperação.'));
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setInfo('');

    const validationError = validatePassword();
    if (validationError) {
      setError(validationError);
      return;
    }

    if (!codeRequested) {
      setError('Primeiro solicite o código de recuperação.');
      return;
    }

    if (codigo.trim().length !== 6) {
      setError('Informe o código de 6 dígitos para redefinir a senha.');
      return;
    }

    setSubmitting(true);
    try {
      await resetPassword({
        email,
        codigo,
        nova_senha: novaSenha,
      });
      navigate('/login', {
        state: {
          email,
          info: 'Senha redefinida. Agora você já pode entrar com a nova senha.',
        },
      });
    } catch (error) {
      setError(getApiErrorMessage(error, 'Não foi possível redefinir a senha. Confira o código e tente de novo.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card auth-card-wide">
        <h1>Recuperar acesso</h1>
        <p className="auth-subtitle">Confirme seu email com um código e defina uma nova senha.</p>

        {error ? <div className="alert error">{error}</div> : null}
        {info ? <div className="alert success">{info}</div> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Email</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>

          <button
            type="button"
            className="secondary-button"
            onClick={() => void handleRequestCode()}
            disabled={sendingCode}
          >
            {sendingCode ? 'Enviando código...' : 'Pedir código de recuperação'}
          </button>

          {codeRequested ? (
            <>
              <label className="field">
                <span>Código de verificação</span>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={codigo}
                  onChange={(event) => setCodigo(event.target.value.replace(/\D/g, ''))}
                  placeholder="Código preenchido automaticamente no modo local"
                  required
                />
              </label>

              <div className="split-fields">
                <label className="field">
                  <span>Nova senha</span>
                  <PasswordInput value={novaSenha} onChange={setNovaSenha} required />
                </label>

                <label className="field">
                  <span>Confirmar nova senha</span>
                  <PasswordInput value={confirmNovaSenha} onChange={setConfirmNovaSenha} required />
                </label>
              </div>
            </>
          ) : null}

          <button type="submit" disabled={submitting}>
            {submitting ? 'Salvando nova senha...' : 'Redefinir senha'}
          </button>
        </form>

        <p className="auth-footer">
          Lembrou da senha? <Link to="/login">Voltar para login</Link>
        </p>
      </div>
    </div>
  );
}
