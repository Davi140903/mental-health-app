import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { PsychologistPatientDetail, PsychologistTriageRequest, QuestionnaireResult } from '../types/app';

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

function questionnaireLabel(result: QuestionnaireResult) {
  return result.tipo === 'phq9' ? 'PHQ-9' : 'GAD-7';
}

function moodLabel(value: number) {
  const labels: Record<number, string> = {
    1: 'Muito dificil',
    2: 'Pesado',
    3: 'Instavel',
    4: 'Mais favoravel',
    5: 'Bem',
  };

  return labels[value] ?? `${value}/5`;
}

export default function PsychologistDashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [requests, setRequests] = useState<PsychologistTriageRequest[]>([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [patientDetail, setPatientDetail] = useState<PsychologistPatientDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');

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

  const handleSelectRequest = async (request: PsychologistTriageRequest) => {
    if (selectedRequestId === request.id) {
      setSelectedRequestId(null);
      setPatientDetail(null);
      setDetailError('');
      return;
    }

    setSelectedRequestId(request.id);
    setDetailLoading(true);
    setDetailError('');

    try {
      const detail = await appService.getPsychologistPatientDetail(request.id);
      setPatientDetail(detail);
    } catch {
      setPatientDetail(null);
      setDetailError('Nao foi possivel abrir os detalhes deste paciente agora.');
    } finally {
      setDetailLoading(false);
    }
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
              <article
                key={request.id}
                className={`triage-request-card ${selectedRequestId === request.id ? 'active' : ''}`}
              >
                <button type="button" className="triage-request-main" onClick={() => void handleSelectRequest(request)}>
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
                </button>

                {selectedRequestId === request.id ? (
                  <div className="patient-detail-panel">
                    {detailLoading ? <div className="empty-state">Abrindo detalhes do paciente...</div> : null}
                    {detailError ? <div className="alert error">{detailError}</div> : null}

                    {!detailLoading && patientDetail ? (
                      <>
                        <div className="patient-detail-header">
                          <div>
                            <span className="field-label">Preparacao para primeira consulta</span>
                            <h4>{patientDetail.user.nome}</h4>
                            <p>{patientDetail.user.email}</p>
                          </div>
                          <div className="triage-time">
                            <span>Gerado em</span>
                            <strong>{formatDateTime(patientDetail.generated_at)}</strong>
                          </div>
                        </div>

                        <div className="patient-detail-grid">
                          <section className="patient-detail-card wide">
                            <span className="field-label">Relatorio da Lia</span>
                            <p>
                              {patientDetail.current_request.interaction?.report ??
                                patientDetail.current_request.interaction?.summary ??
                                'Ainda nao ha um relatorio detalhado da Lia para este pedido.'}
                            </p>
                          </section>

                          <section className="patient-detail-card">
                            <span className="field-label">Memoria breve</span>
                            <p>
                              {patientDetail.lia_memory.recent_summary ??
                                patientDetail.lia_memory.summary ??
                                'Ainda ha pouco historico acumulado deste paciente.'}
                            </p>
                            {patientDetail.lia_memory.topics.length ? (
                              <div className="triage-topic-row compact-tags">
                                {patientDetail.lia_memory.topics.slice(0, 8).map((topic) => (
                                  <span key={topic}>{topic}</span>
                                ))}
                              </div>
                            ) : null}
                          </section>

                          <section className="patient-detail-card">
                            <span className="field-label">Triagens recentes</span>
                            {patientDetail.questionnaires.length ? (
                              <div className="patient-mini-list">
                                {patientDetail.questionnaires.slice(0, 5).map((item) => (
                                  <div key={item.id}>
                                    <strong>{questionnaireLabel(item)}</strong>
                                    <span>
                                      {item.pontuacao} pontos, {item.classificacao}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p>Nenhuma triagem PHQ/GAD registrada ainda.</p>
                            )}
                          </section>

                          <section className="patient-detail-card">
                            <span className="field-label">Humor recente</span>
                            {patientDetail.moods.length ? (
                              <div className="patient-mini-list">
                                {patientDetail.moods.slice(0, 5).map((mood) => (
                                  <div key={mood.id}>
                                    <strong>{moodLabel(mood.valor)}</strong>
                                    <span>{mood.nota || formatDateTime(mood.criado_em)}</span>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p>Nenhum registro de humor salvo ainda.</p>
                            )}
                          </section>

                          <section className="patient-detail-card wide">
                            <span className="field-label">Conversas recentes com a Lia</span>
                            {patientDetail.lia_memory.recent_conversations.length ? (
                              <div className="patient-conversation-list">
                                {patientDetail.lia_memory.recent_conversations.slice(0, 4).map((interaction) => (
                                  <article key={interaction.id ?? interaction.created_at}>
                                    <strong>{formatDateTime(interaction.created_at)}</strong>
                                    <p>{interaction.report ?? interaction.summary}</p>
                                  </article>
                                ))}
                              </div>
                            ) : (
                              <p>Ainda nao ha conversas recentes para exibir.</p>
                            )}
                          </section>
                        </div>
                      </>
                    ) : null}
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
