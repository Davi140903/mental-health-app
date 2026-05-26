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

export default function Register() {
  const { register, requestRegisterCode } = useAuth();
  const navigate = useNavigate();
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [codigo, setCodigo] = useState('');
  const [consentimentoLgpd, setConsentimentoLgpd] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [codeRequested, setCodeRequested] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const validateForm = () => {
    if (password.length < 6) {
      return 'A senha precisa ter pelo menos 6 caracteres.';
    }
    if (password !== confirmPassword) {
      return 'As senhas não coincidem.';
    }
    if (!consentimentoLgpd) {
      return 'Você precisa aceitar o termo de privacidade para continuar.';
    }
    return '';
  };

  const handleRequestCode = async () => {
    setError('');
    setInfo('');

    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSendingCode(true);
    try {
      const response = await requestRegisterCode(email);
      setCodeRequested(true);
      if (response.debug_code) {
        setCodigo(response.debug_code);
      }
      setInfo(buildCodeMessage(response.debug_code, 'Código de cadastro enviado.'));
    } catch (error) {
      setError(getApiErrorMessage(error, 'Não foi possível enviar o código. Verifique se o email já está em uso.'));
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setInfo('');

    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    if (!codeRequested) {
      setError('Primeiro solicite o código de verificação do email.');
      return;
    }

    if (codigo.trim().length !== 6) {
      setError('Informe o código de 6 dígitos para concluir o cadastro.');
      return;
    }

    setSubmitting(true);
    try {
      await register({
        email,
        nome,
        password,
        consentimento_lgpd: consentimentoLgpd,
        codigo,
      });
      navigate('/login', {
        state: {
          email,
          info: 'Conta criada. Agora solicite um código para entrar com segurança.',
        },
      });
    } catch (error) {
      setError(getApiErrorMessage(error, 'Não foi possível criar a conta. Confira o código e tente de novo.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card auth-card-wide">
        <h1>Criar conta</h1>
        <p className="auth-subtitle">Confirme seu email com um código antes de concluir.</p>

        {error ? <div className="alert error">{error}</div> : null}
        {info ? <div className="alert success">{info}</div> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <div className="split-fields">
            <label className="field">
              <span>Nome</span>
              <input type="text" value={nome} onChange={(event) => setNome(event.target.value)} required />
            </label>

            <label className="field">
              <span>Email</span>
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </label>
          </div>

          <div className="split-fields">
            <label className="field">
              <span>Senha</span>
              <PasswordInput value={password} onChange={setPassword} required />
            </label>

            <label className="field">
              <span>Confirmar senha</span>
              <PasswordInput value={confirmPassword} onChange={setConfirmPassword} required />
            </label>
          </div>

          <label className="consent-box">
            <input
              type="checkbox"
              checked={consentimentoLgpd}
              onChange={(event) => setConsentimentoLgpd(event.target.checked)}
            />
            <span>
              Concordo com o uso dos meus dados no aplicativo e posso exportar ou excluir essas informacoes depois.
            </span>
          </label>

          <button
            type="button"
            className="secondary-button"
            onClick={() => void handleRequestCode()}
            disabled={sendingCode}
          >
            {sendingCode ? 'Enviando código...' : 'Pedir código por email'}
          </button>

          {codeRequested ? (
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
          ) : null}

          <button type="submit" disabled={submitting}>
            {submitting ? 'Criando conta...' : 'Criar conta'}
          </button>
        </form>

        <p className="auth-footer">
          Já possui conta? <Link to="/login">Entrar</Link>
        </p>
      </div>
    </div>
  );
}
