import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { useAuth } from '../contexts/useAuth';
import { authService } from '../services/auth';

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(new Date(value));
}

export default function Profile() {
  const navigate = useNavigate();
  const { user, updateProfile, logout } = useAuth();
  const [nome, setNome] = useState(user?.nome ?? '');
  const [consentimentoLgpd, setConsentimentoLgpd] = useState(Boolean(user?.consentimento_lgpd));
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setNome(user?.nome ?? '');
    setConsentimentoLgpd(Boolean(user?.consentimento_lgpd));
  }, [user]);

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage('');
    setError('');
    setSaving(true);

    try {
      await updateProfile({
        nome,
        consentimento_lgpd: consentimentoLgpd,
      });
      setMessage('Perfil atualizado com sucesso.');
    } catch {
      setError('Nao foi possivel atualizar o perfil.');
    } finally {
      setSaving(false);
    }
  };

  const handleExport = async () => {
    setMessage('');
    setError('');
    setExporting(true);

    try {
      const payload = await authService.exportData();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'mental-health-export.json';
      link.click();
      window.URL.revokeObjectURL(url);
      setMessage('Exportacao concluida.');
    } catch {
      setError('Nao foi possivel exportar os dados.');
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Deseja realmente excluir sua conta e todos os dados salvos?')) {
      return;
    }

    setMessage('');
    setError('');
    setDeleting(true);

    try {
      await authService.deleteProfile();
      logout();
      navigate('/register');
    } catch {
      setError('Nao foi possivel excluir a conta.');
      setDeleting(false);
    }
  };

  return (
    <Layout>
      <section className="split-layout">
        <article className="section-card">
          <div className="section-heading">
            <div>
              <h2>Dados da conta</h2>
            </div>
          </div>

          {message ? <div className="alert success">{message}</div> : null}
          {error ? <div className="alert error">{error}</div> : null}

          <form className="form-grid" onSubmit={handleSave}>
            <label className="field">
              <span>Nome</span>
              <input type="text" value={nome} onChange={(event) => setNome(event.target.value)} required />
            </label>

            <label className="consent-box">
              <input
                type="checkbox"
                checked={consentimentoLgpd}
                onChange={(event) => setConsentimentoLgpd(event.target.checked)}
              />
              <span>Manter consentimento ativo para tratamento dos dados do aplicativo.</span>
            </label>

            <button type="submit" disabled={saving}>
              {saving ? 'Salvando...' : 'Salvar alteracoes'}
            </button>
          </form>
        </article>

        <article className="section-card">
          <div className="section-heading">
            <div>
              <h2>Privacidade</h2>
            </div>
          </div>

          <div className="stack-list">
            <div className="summary-block">
              <span className="stat-label">Email da conta</span>
              <strong>{user?.email}</strong>
            </div>
            <div className="summary-block">
              <span className="stat-label">Conta criada em</span>
              <p>{user ? formatDate(user.criado_em) : '--'}</p>
            </div>
            <div className="summary-block">
              <span className="stat-label">Acoes</span>
              <p>Voce pode exportar ou excluir seus dados.</p>
            </div>
          </div>

          <div className="toolbar actions-toolbar">
            <button type="button" className="secondary-button" onClick={handleExport} disabled={exporting}>
              {exporting ? 'Exportando...' : 'Exportar dados'}
            </button>
            <button type="button" className="danger-button" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Excluindo...' : 'Excluir conta'}
            </button>
          </div>
        </article>
      </section>
    </Layout>
  );
}

