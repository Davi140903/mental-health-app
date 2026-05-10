import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { AdminPsychologistInput } from '../types/app';
import type { Usuario } from '../types/auth';

const emptyForm: AdminPsychologistInput = {
  email: '',
  nome: '',
  password: '',
  consentimento_lgpd: true,
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
  }).format(new Date(value));
}

export default function AdminDashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [psychologists, setPsychologists] = useState<Usuario[]>([]);
  const [form, setForm] = useState<AdminPsychologistInput>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  const loadPsychologists = async () => {
    setLoading(true);
    setError('');

    try {
      const response = await appService.listAdminPsychologists();
      setPsychologists(response);
    } catch {
      setError('Nao foi possivel carregar os psicologos agora.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPsychologists();
  }, []);

  const resetForm = () => {
    setForm(emptyForm);
    setEditingId(null);
  };

  const handleEdit = (psychologist: Usuario) => {
    setEditingId(psychologist.id);
    setForm({
      email: psychologist.email,
      nome: psychologist.nome,
      password: '',
      consentimento_lgpd: psychologist.consentimento_lgpd,
    });
    setFeedback('');
    setError('');
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setFeedback('');
    setError('');

    try {
      if (editingId) {
        await appService.updateAdminPsychologist(editingId, {
          ...form,
          password: form.password?.trim() || undefined,
        });
        setFeedback('Login do psicologo atualizado.');
      } else {
        if (!form.password?.trim()) {
          setError('Informe uma senha inicial para o psicologo.');
          return;
        }
        await appService.createAdminPsychologist({
          ...form,
          password: form.password.trim(),
        });
        setFeedback('Login do psicologo criado.');
      }

      resetForm();
      await loadPsychologists();
    } catch {
      setError('Nao foi possivel salvar este psicologo. Verifique se o email ja existe.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (psychologist: Usuario) => {
    const confirmed = window.confirm(`Remover o acesso de ${psychologist.nome}?`);
    if (!confirmed) {
      return;
    }

    setError('');
    setFeedback('');

    try {
      await appService.deleteAdminPsychologist(psychologist.id);
      setFeedback('Login do psicologo removido.');
      await loadPsychologists();
      if (editingId === psychologist.id) {
        resetForm();
      }
    } catch {
      setError('Nao foi possivel remover este psicologo agora.');
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="admin-app-shell">
      <header className="admin-topbar">
        <div>
          <span className="admin-role-pill">Area ADM</span>
          <h1>Controle de psicologos</h1>
          <p>{user?.nome ? `Ola, ${user.nome}.` : 'Gerencie os acessos profissionais da plataforma.'}</p>
        </div>

        <button type="button" className="admin-ghost-button" onClick={handleLogout}>
          Sair
        </button>
      </header>

      <main className="admin-page">
        <section className="admin-summary-grid">
          <article className="admin-metric">
            <span>Psicologos cadastrados</span>
            <strong>{psychologists.length}</strong>
            <p>Contas profissionais criadas pelo ADM.</p>
          </article>

          <article className="admin-metric">
            <span>Permissao</span>
            <strong>ADM</strong>
            <p>Somente esta area cria ou remove logins de psicologos.</p>
          </article>
        </section>

        <section className="admin-workspace">
          <div className="admin-panel">
            <div className="admin-toolbar">
              <div>
                <h2>{editingId ? 'Editar psicologo' : 'Novo psicologo'}</h2>
                <p>Crie o login que sera usado na fila de triagem.</p>
              </div>
            </div>

            {error ? <div className="alert error">{error}</div> : null}
            {feedback ? <div className="alert success">{feedback}</div> : null}

            <form className="admin-form" onSubmit={handleSubmit}>
              <label>
                Nome
                <input
                  value={form.nome}
                  onChange={(event) => setForm((current) => ({ ...current, nome: event.target.value }))}
                  minLength={2}
                  required
                  placeholder="Ex.: Dra. Marina"
                />
              </label>

              <label>
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                  required
                  placeholder="psicologo@email.com"
                />
              </label>

              <label>
                {editingId ? 'Nova senha opcional' : 'Senha inicial'}
                <input
                  type="password"
                  value={form.password ?? ''}
                  onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                  minLength={editingId ? undefined : 6}
                  required={!editingId}
                  placeholder={editingId ? 'Deixe vazio para manter a senha' : 'Minimo de 6 caracteres'}
                />
              </label>

              <label className="admin-check">
                <input
                  type="checkbox"
                  checked={form.consentimento_lgpd}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, consentimento_lgpd: event.target.checked }))
                  }
                />
                Termo de privacidade confirmado para esta conta
              </label>

              <div className="admin-form-actions">
                <button type="submit" disabled={saving}>
                  {saving ? 'Salvando...' : editingId ? 'Salvar alteracoes' : 'Criar login'}
                </button>

                {editingId ? (
                  <button type="button" className="admin-ghost-button" onClick={resetForm}>
                    Cancelar edicao
                  </button>
                ) : null}
              </div>
            </form>
          </div>

          <div className="admin-panel">
            <div className="admin-toolbar">
              <div>
                <h2>Logins ativos</h2>
                <p>Use esta lista para revisar, editar ou remover acessos.</p>
              </div>
            </div>

            {loading ? <div className="empty-state">Carregando psicologos...</div> : null}
            {!loading && !psychologists.length ? (
              <div className="empty-state">Nenhum psicologo cadastrado ainda.</div>
            ) : null}

            <div className="admin-list">
              {psychologists.map((psychologist) => (
                <article key={psychologist.id} className="admin-card">
                  <div>
                    <h3>{psychologist.nome}</h3>
                    <p>{psychologist.email}</p>
                    <span>Criado em {formatDate(psychologist.criado_em)}</span>
                  </div>

                  <div className="admin-card-actions">
                    <button type="button" className="admin-ghost-button" onClick={() => handleEdit(psychologist)}>
                      Editar
                    </button>
                    <button type="button" className="admin-danger-button" onClick={() => void handleDelete(psychologist)}>
                      Remover
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
