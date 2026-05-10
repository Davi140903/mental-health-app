import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { PsychologistTriageRequest } from '../types/app';

const statusOptions = [
  { value: '', label: 'Todos' },
  { value: 'pending', label: 'Aguardando' },
  { value: 'scheduled', label: 'Agendados' },
];

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Sem horario definido';
  }

  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: 'Aguardando agendamento',
    scheduled: 'Triagem agendada',
    completed: 'Concluida',
    cancelled: 'Cancelada',
  };

  return labels[status] ?? status;
}

function extractMainText(request: PsychologistTriageRequest) {
  const report = request.interaction?.report ?? '';
  const summary = request.interaction?.summary ?? '';
  const source = report || summary;

  if (!source) {
    return 'Ainda nao ha resumo da Lia ligado a este pedido.';
  }

  return source.length > 520 ? `${source.slice(0, 520).trim()}...` : source;
}

export default function PsychologistDashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [requests, setRequests] = useState<PsychologistTriageRequest[]>([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;

    const loadRequests = async () => {
      setLoading(true);
      setError('');

      try {
        const response = await appService.listPsychologistTriageRequests(statusFilter || undefined);
        if (active) {
          setRequests(response);
        }
      } catch {
        if (active) {
          setError('Nao foi possivel carregar os pedidos de triagem agora.');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadRequests();

    return () => {
      active = false;
    };
  }, [statusFilter]);

  const pendingCount = requests.filter((item) => item.status === 'pending').length;
  const scheduledCount = requests.filter((item) => item.status === 'scheduled').length;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="psychologist-app-shell">
      <header className="psychologist-topbar">
        <div>
          <span className="role-pill">Area do psicologo</span>
          <h1>Fila de triagem</h1>
          <p>{user?.nome ? `Ola, ${user.nome}.` : 'Acompanhe os pedidos que chegaram pela Lia.'}</p>
        </div>

        <button type="button" className="psychologist-ghost-button" onClick={handleLogout}>
          Sair
        </button>
      </header>

      <main className="psychologist-page">
        <section className="psychologist-summary-grid">
          <article className="psychologist-metric">
            <span>Pedidos visiveis</span>
            <strong>{requests.length}</strong>
            <p>Solicitacoes encontradas para o filtro atual.</p>
          </article>

          <article className="psychologist-metric">
            <span>Aguardando</span>
            <strong>{pendingCount}</strong>
            <p>Usuarios que ainda precisam concluir o agendamento.</p>
          </article>

          <article className="psychologist-metric">
            <span>Agendados</span>
            <strong>{scheduledCount}</strong>
            <p>Triagens ja vinculadas a horario e profissional.</p>
          </article>
        </section>

        <section className="psychologist-workspace">
          <div className="psychologist-toolbar">
            <div>
              <h2>Solicitacoes de atendimento</h2>
              <p>Veja o contexto inicial organizado pela Lia antes da triagem.</p>
            </div>

            <div className="segmented-control" aria-label="Filtrar pedidos">
              {statusOptions.map((option) => (
                <button
                  key={option.value || 'all'}
                  type="button"
                  className={statusFilter === option.value ? 'active' : ''}
                  onClick={() => setStatusFilter(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {error ? <div className="alert error">{error}</div> : null}
          {loading ? <div className="empty-state">Carregando pedidos...</div> : null}

          {!loading && !requests.length ? (
            <div className="empty-state">Ainda nao ha pedidos para este filtro.</div>
          ) : null}

          <div className="triage-request-list">
            {requests.map((request) => (
              <article key={request.id} className="triage-request-card">
                <div className="triage-request-header">
                  <div>
                    <span className={`status-badge status-${request.status}`}>{statusLabel(request.status)}</span>
                    <h3>{request.user.nome}</h3>
                    <p>{request.user.email}</p>
                  </div>

                  <div className="triage-time">
                    <span>Pedido</span>
                    <strong>{formatDateTime(request.requested_at)}</strong>
                  </div>
                </div>

                <div className="triage-request-grid">
                  <div>
                    <span className="field-label">Horario</span>
                    <p>{formatDateTime(request.scheduled_for)}</p>
                  </div>
                  <div>
                    <span className="field-label">Profissional</span>
                    <p>{request.psychologist_name ?? 'Ainda nao definido'}</p>
                  </div>
                  <div>
                    <span className="field-label">Origem</span>
                    <p>{request.interaction ? 'Conversa com a Lia' : 'Pedido sem conversa vinculada'}</p>
                  </div>
                </div>

                <div className="triage-report">
                  <span className="field-label">Resumo para triagem</span>
                  <p>{extractMainText(request)}</p>
                </div>

                {request.interaction?.topics?.length ? (
                  <div className="triage-topic-row">
                    {request.interaction.topics.slice(0, 6).map((topic) => (
                      <span key={topic}>{topic}</span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
