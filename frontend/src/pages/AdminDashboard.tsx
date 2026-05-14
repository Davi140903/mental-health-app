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
      setError('N?o foi poss?vel carregar os psic?logos agora.');
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
        setFeedback('Login do psic?logo atualizado.');
      } else {
        if (!form.password?.trim()) {
          setError('Informe uma senha inicial para o psic?logo.');
          return;
        }
        await appService.createAdminPsychologist({
          ...form,
          password: form.password.trim(),
        });
        setFeedback('Login do psic?logo criado.');
      }

      resetForm();
      await loadPsychologists();
    } catch {
      setError('N?o foi poss?vel salvar este psic?logo. Verifique se o email j? existe.');
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
      setFeedback('Login do psic?logo removido.');
      await loadPsychologists();
      if (editingId === psychologist.id) {
        resetForm();
      }
    } catch {
      setError('N?o foi poss?vel remover este psic?logo agora.');
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
          <span className="admin-role-pill">Painel administrativo</span>
          <h1>Gestao de acessos profissionais</h1>
          <p>
            {user?.nome
              ? `Operador: ${user.nome}`
              : 'Controle os perfis profissionais autorizados na plataforma.'}
          </p>
        </div>

        <button type="button" className="admin-ghost-button" onClick={handleLogout}>
          Sair
        </button>
      </header>

      <main className="admin-page">
        <section className="admin-summary-grid">
          <article className="admin-metric">
            <span>Profissionais ativos</span>
            <strong>{psychologists.length}</strong>
            <p>Contas com permissao de acesso ao painel de triagem.</p>
          </article>

          <article className="admin-metric">
            <span>Escopo do modulo</span>
            <strong>CRUD</strong>
            <p>Criar, revisar, atualizar e remover acessos profissionais.</p>
          </article>
        </section>

        <section className="admin-workspace">
          <div className="admin-panel">
            <div className="admin-toolbar">
              <div>
                <h2>{editingId ? 'Editar psic?logo' : 'Novo psic?logo'}</h2>
                <p>Cadastre o profissional que podera acessar solicitacoes de triagem.</p>
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
                  placeholder="psic?logo@email.com"
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
                  {saving ? 'Salvando...' : editingId ? 'Salvar altera??es' : 'Criar login'}
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
                <h2>Registro de profissionais</h2>
                <p>Lista administrativa dos logins autorizados para atendimento.</p>
              </div>
            </div>

            {loading ? <div className="empty-state">Carregando psicólogos...</div> : null}
            {!loading && !psychologists.length ? (
              <div className="empty-state">Nenhum psicólogo cadastrado ainda.</div>
            ) : null}

            {psychologists.length ? (
              <div className="admin-table-shell">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Profissional</th>
                      <th>Email</th>
                      <th>Criado em</th>
                      <th>Acoes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {psychologists.map((psychologist) => (
                      <tr key={psychologist.id}>
                        <td>
                          <strong>{psychologist.nome}</strong>
                          <span>Psicologo</span>
                        </td>
                        <td>{psychologist.email}</td>
                        <td>{formatDate(psychologist.criado_em)}</td>
                        <td>
                          <div className="admin-card-actions">
                            <button type="button" className="admin-ghost-button" onClick={() => handleEdit(psychologist)}>
                              Editar
                            </button>
                            <button
                              type="button"
                              className="admin-danger-button"
                              onClick={() => void handleDelete(psychologist)}
                            >
                              Remover
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </section>
      </main>
    </div>
  );
}
