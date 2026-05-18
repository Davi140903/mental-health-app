import { useEffect, useState } from 'react';
import AppFooter from '../components/AppFooter';
import AppHeader from '../components/AppHeader';
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

function maskEmail(value: string) {
  const [localPart, domain = ''] = value.split('@');
  const visibleLocal = localPart.slice(0, 2);
  return `${visibleLocal}${'•'.repeat(Math.max(localPart.length - 2, 3))}@${domain}`;
}

export default function AdminDashboard() {
  const { user } = useAuth();
  const [psychologists, setPsychologists] = useState<Usuario[]>([]);
  const [form, setForm] = useState<AdminPsychologistInput>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');
  const [revealedIds, setRevealedIds] = useState<Set<string>>(() => new Set());

  const loadPsychologists = async () => {
    setLoading(true);
    setError('');

    try {
      const response = await appService.listAdminPsychologists();
      setPsychologists(response);
    } catch {
      setError('Não foi possível carregar os psicólogos agora.');
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

  const toggleReveal = (psychologistId: string) => {
    setRevealedIds((current) => {
      const next = new Set(current);
      if (next.has(psychologistId)) {
        next.delete(psychologistId);
      } else {
        next.add(psychologistId);
      }
      return next;
    });
  };

  const handleEdit = (psychologist: Usuario) => {
    setRevealedIds((current) => new Set(current).add(psychologist.id));
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
        setFeedback('Login do psicólogo atualizado.');
      } else {
        if (!form.password?.trim()) {
          setError('Informe uma senha inicial para o psicólogo.');
          return;
        }
        await appService.createAdminPsychologist({
          ...form,
          password: form.password.trim(),
        });
        setFeedback('Login do psicólogo criado.');
      }

      resetForm();
      await loadPsychologists();
    } catch {
      setError('Não foi possível salvar este psicólogo. Verifique se o email já existe.');
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
      setFeedback('Login do psicólogo removido.');
      await loadPsychologists();
      if (editingId === psychologist.id) {
        resetForm();
      }
    } catch {
      setError('Não foi possível remover este psicólogo agora.');
    }
  };

  return (
    <div className="admin-app-shell">
      <AppHeader
        tone="admin"
        brand="Lia"
        subtitle={user?.nome ? `Operador: ${user.nome}` : 'Área administrativa'}
        links={[{ to: '/admin', label: 'Psicólogos' }]}
      />
      <div className="admin-page-heading">
        <div>
          <span className="admin-role-pill">Painel administrativo</span>
          <h1>Gestao de acessos profissionais</h1>
          <p>
            Controle os perfis profissionais autorizados na plataforma.
          </p>
        </div>
      </div>

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
                <h2>{editingId ? 'Editar psicólogo' : 'Novo psicólogo'}</h2>
                <p>Cadastre o profissional que poderá acessar solicitações de triagem.</p>
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
                  placeholder={editingId ? 'Deixe vazio para manter a senha' : 'Mínimo de 6 caracteres'}
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
                  {saving ? 'Salvando...' : editingId ? 'Salvar alterações' : 'Criar login'}
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
                <p>Emails protegidos por padrão; revele apenas quando houver necessidade administrativa.</p>
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
                          <span>Psicólogo</span>
                        </td>
                        <td>{revealedIds.has(psychologist.id) ? psychologist.email : maskEmail(psychologist.email)}</td>
                        <td>{formatDate(psychologist.criado_em)}</td>
                        <td>
                          <div className="admin-card-actions">
                            <button
                              type="button"
                              className="admin-ghost-button"
                              onClick={() => toggleReveal(psychologist.id)}
                            >
                              {revealedIds.has(psychologist.id) ? 'Ocultar' : 'Mostrar'}
                            </button>
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
      <AppFooter tone="admin" />
    </div>
  );
}
