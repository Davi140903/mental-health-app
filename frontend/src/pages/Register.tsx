import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [consentimentoLgpd, setConsentimentoLgpd] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');

    if (password.length < 6) {
      setError('A senha precisa ter pelo menos 6 caracteres.');
      return;
    }

    if (password !== confirmPassword) {
      setError('As senhas nao coincidem.');
      return;
    }

    if (!consentimentoLgpd) {
      setError('Voce precisa aceitar o termo de privacidade para continuar.');
      return;
    }

    setSubmitting(true);

    try {
      await register({
        email,
        nome,
        password,
        consentimento_lgpd: consentimentoLgpd,
      });
      navigate('/dashboard');
    } catch {
      setError('Nao foi possivel criar a conta. Verifique se o email ja esta em uso.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card auth-card-wide">
        <h1>Criar conta</h1>
        <p className="auth-subtitle">Leva so alguns instantes.</p>

        {error ? <div className="alert error">{error}</div> : null}

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
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>

            <label className="field">
              <span>Confirmar senha</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
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

          <button type="submit" disabled={submitting}>
            {submitting ? 'Criando conta...' : 'Criar conta'}
          </button>
        </form>

        <p className="auth-footer">
          Ja possui conta? <Link to="/login">Entrar</Link>
        </p>
      </div>
    </div>
  );
}


