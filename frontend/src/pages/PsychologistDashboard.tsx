import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { LiaRecentInteraction, PsychologistPatientDetail, PsychologistTriageRequest, QuestionnaireResult } from '../types/app';

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
  const summary = request.interaction?.summary ?? '';
  const source = summary;

  if (!source) {
    return 'Pedido recebido pela Lia, ainda sem sintese breve vinculada.';
  }

  return source.length > 220 ? `${source.slice(0, 220).trim()}...` : source;
}

function splitSummaryTopics(value?: string | null) {
  const cleaned = (value ?? '').trim().replace(/\.$/, '');
  if (!cleaned) {
    return [];
  }

  return cleaned
    .split(';')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 4);
}

function isRawConversationText(value?: string | null) {
  const normalized = normalizeMessageForCompare(value ?? '');
  return normalized.includes('|') || normalized.length > 160 || normalized.includes('oi lia');
}

function patientFirstName(name: string) {
  return name.trim().split(' ')[0] || 'Usuario';
}

function hasTranscript(interaction: LiaRecentInteraction) {
  return Boolean(interaction.transcript?.length);
}

function normalizeMessageForCompare(value: string) {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function getCleanTranscript(interaction: LiaRecentInteraction) {
  const cleaned: NonNullable<LiaRecentInteraction['transcript']> = [];
  let previousKey = '';

  for (const message of interaction.transcript ?? []) {
    const content = message.content.trim();
    if (!content) {
      continue;
    }

    const key = `${message.role}:${normalizeMessageForCompare(content)}`;
    if (key === previousKey) {
      continue;
    }

    cleaned.push({ ...message, content });
    previousKey = key;
  }

  return cleaned;
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

function moodDescription(value: number) {
  const labels: Record<number, string> = {
    1: 'Registro indica um momento mais dificil.',
    2: 'Registro indica um periodo pesado.',
    3: 'Registro indica oscilacao ou instabilidade.',
    4: 'Registro indica um momento um pouco mais favoravel.',
    5: 'Registro indica um momento positivo.',
  };

  return labels[value] ?? 'Registro de humor salvo no app.';
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
  const [noteModalOpen, setNoteModalOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState('');
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteFeedback, setNoteFeedback] = useState('');

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
      setNoteDraft(detail.psychologist_note?.content ?? '');
    } catch {
      setPatientDetail(null);
      setDetailError('Nao foi possivel abrir os detalhes deste paciente agora.');
    } finally {
      setDetailLoading(false);
    }
  };

  const escapeHtml = (value: string) =>
    value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');

  const openPrintDocument = (title: string, html: string) => {
    const printWindow = window.open('', '_blank', 'width=900,height=720');
    if (!printWindow) {
      return;
    }

    printWindow.document.write(`
      <!doctype html>
      <html lang="pt-BR">
        <head>
          <meta charset="utf-8" />
          <title>${escapeHtml(title)}</title>
          <style>
            body { font-family: Georgia, 'Times New Roman', serif; color: #1f2933; margin: 32px; line-height: 1.5; }
            header { border-bottom: 2px solid #315d74; margin-bottom: 20px; padding-bottom: 12px; }
            h1 { margin: 0 0 4px; font-size: 24px; }
            h2 { margin-top: 24px; font-size: 17px; color: #315d74; border-bottom: 1px solid #d8e3e8; padding-bottom: 4px; }
            p { margin: 6px 0; }
            .meta { color: #5f7480; font-size: 13px; }
            .box { border: 1px solid #d8e3e8; padding: 12px; margin: 10px 0; border-radius: 6px; }
            .chat-session { border: 1px solid #d8e3e8; padding: 14px; margin: 12px 0; border-radius: 12px; background: #f8fbfc; }
            .chat-message { max-width: 78%; padding: 9px 11px; margin: 8px 0; border-radius: 12px; border: 1px solid #d8e3e8; }
            .chat-message.lia { background: #ffffff; border-bottom-left-radius: 4px; }
            .chat-message.user { margin-left: auto; background: #e7f1f6; border-bottom-right-radius: 4px; }
            .chat-author { display: block; font: 700 11px Arial, sans-serif; letter-spacing: 0.04em; text-transform: uppercase; color: #315d74; margin-bottom: 3px; }
            .chat-message p { margin: 0; }
            .chat-legacy-note { border: 1px dashed #b8ccd6; background: #ffffff; border-radius: 10px; padding: 12px; }
            .chat-legacy-note strong { display: block; color: #315d74; margin-bottom: 4px; }
            .chat-legacy-note p { margin: 0; color: #5f7480; }
            ul { padding-left: 18px; }
            @media print { body { margin: 20mm; } button { display: none; } }
          </style>
        </head>
        <body>${html}</body>
      </html>
    `);
    printWindow.document.close();
    printWindow.focus();
    printWindow.print();
  };

  const buildConversationPrintHtml = (interaction: LiaRecentInteraction, patientName: string) => {
    if (!hasTranscript(interaction)) {
      return `
        <div class="chat-session legacy">
          <p class="meta">${formatDateTime(interaction.created_at)}</p>
          <div class="chat-legacy-note">
            <strong>Registro antigo</strong>
            <p>Esta conversa foi salva antes do app guardar a transcricao completa. O resumo clinico ja aparece acima; as proximas conversas serao exibidas aqui como chat, com falas da Lia e do paciente.</p>
          </div>
        </div>
      `;
    }

    const firstName = patientFirstName(patientName);
    const messages = getCleanTranscript(interaction)
      .map((message) => {
        const author = message.role === 'assistant' ? 'Lia' : firstName;
        return `
          <div class="chat-message ${message.role === 'assistant' ? 'lia' : 'user'}">
            <span class="chat-author">${escapeHtml(author)}</span>
            <p>${escapeHtml(message.content)}</p>
          </div>
        `;
      })
      .join('');

    return `
      <div class="chat-session">
        <p class="meta">${formatDateTime(interaction.created_at)}</p>
        ${messages}
      </div>
    `;
  };

  const buildPatientReportHtml = (detail: PsychologistPatientDetail) => {
    const note = noteDraft.trim() || detail.psychologist_note?.content || 'Sem anotacoes registradas.';
    const questionnaires = detail.questionnaires.length
      ? detail.questionnaires
          .map((item) => `<li>${questionnaireLabel(item)}: ${item.pontuacao} pontos, ${escapeHtml(item.classificacao)}</li>`)
          .join('')
      : '<li>Nenhuma triagem PHQ/GAD registrada.</li>';
    const moods = detail.moods.length
      ? detail.moods
          .slice(0, 8)
          .map((mood) => `<li>${moodLabel(mood.valor)} - ${escapeHtml(formatDateTime(mood.criado_em))}</li>`)
          .join('')
      : '<li>Nenhum registro de humor salvo.</li>';
    const conversations = detail.lia_memory.recent_conversations.length
      ? detail.lia_memory.recent_conversations
          .slice(0, 5)
          .map((interaction) => buildConversationPrintHtml(interaction, detail.user.nome))
          .join('')
      : '<p>Nenhuma conversa recente registrada.</p>';

    return `
      <header>
        <h1>Relatorio de triagem e preparacao</h1>
        <p class="meta">Paciente: ${escapeHtml(detail.user.nome)} | ${escapeHtml(detail.user.email)}</p>
        <p class="meta">Gerado em ${formatDateTime(new Date().toISOString())}</p>
      </header>
      <h2>Resumo da Lia</h2>
      <div class="box"><p>${escapeHtml(
        detail.current_request.interaction?.report ??
          detail.current_request.interaction?.summary ??
          'Ainda nao ha relatorio detalhado da Lia.',
      )}</p></div>
      <h2>Triagens recentes</h2>
      <ul>${questionnaires}</ul>
      <h2>Humor recente</h2>
      <ul>${moods}</ul>
      <h2>Conversas recentes com a Lia</h2>
      ${conversations}
      <h2>Anotacoes do profissional</h2>
      <div class="box"><p>${escapeHtml(note).replaceAll('\\n', '<br />')}</p></div>
    `;
  };

  const handleSaveNote = async () => {
    if (!selectedRequestId) {
      return;
    }

    setNoteSaving(true);
    setNoteFeedback('');
    try {
      const saved = await appService.updatePsychologistPatientNote(selectedRequestId, noteDraft);
      setPatientDetail((current) => (current ? { ...current, psychologist_note: saved } : current));
      setNoteFeedback('Anotacao salva.');
    } catch {
      setNoteFeedback('Nao foi possivel salvar agora.');
    } finally {
      setNoteSaving(false);
    }
  };

  const handleDownloadNote = () => {
    if (!patientDetail) {
      return;
    }

    const content = [
      `Paciente: ${patientDetail.user.nome}`,
      `Email: ${patientDetail.user.email}`,
      `Gerado em: ${formatDateTime(new Date().toISOString())}`,
      '',
      'Anotacoes do profissional:',
      noteDraft.trim() || 'Sem anotacoes registradas.',
    ].join('\n');
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `anotacoes-${patientDetail.user.nome.toLowerCase().replaceAll(' ', '-')}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handlePrintNote = () => {
    if (!patientDetail) {
      return;
    }

    openPrintDocument(
      `Anotacoes - ${patientDetail.user.nome}`,
      `
        <header>
          <h1>Anotacoes do profissional</h1>
          <p class="meta">Paciente: ${escapeHtml(patientDetail.user.nome)} | ${escapeHtml(patientDetail.user.email)}</p>
          <p class="meta">Gerado em ${formatDateTime(new Date().toISOString())}</p>
        </header>
        <div class="box"><p>${escapeHtml(noteDraft.trim() || 'Sem anotacoes registradas.').replaceAll('\\n', '<br />')}</p></div>
      `,
    );
  };

  const handlePrintPatientReport = () => {
    if (!patientDetail) {
      return;
    }

    openPrintDocument(`Relatorio - ${patientDetail.user.nome}`, buildPatientReportHtml(patientDetail));
  };

  return (
    <div className="psychologist-app-shell">
      <header className="psychologist-topbar">
        <div>
          <span className="role-pill">Painel profissional</span>
          <h1>Solicitacoes de triagem</h1>
          <p>{user?.nome ? `Profissional: ${user.nome}` : 'Acompanhe os pedidos que chegaram pela Lia.'}</p>
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
            <p>Registros encontrados para o filtro atual.</p>
          </article>

          <article className="psychologist-metric">
            <span>Aguardando</span>
            <strong>{pendingCount}</strong>
            <p>Pedidos ainda sem horario confirmado.</p>
          </article>

          <article className="psychologist-metric">
            <span>Agendados</span>
            <strong>{scheduledCount}</strong>
            <p>Atendimentos vinculados a horario e profissional.</p>
          </article>
        </section>

        <section className="psychologist-workspace">
          <div className="psychologist-toolbar">
            <div>
              <h2>Registros recebidos</h2>
              <p>Selecione um paciente para abrir o contexto de preparacao da primeira consulta.</p>
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
                      <span>Solicitado em</span>
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
                    <span className="field-label">Ponto inicial</span>
                    {splitSummaryTopics(request.interaction?.summary).length ? (
                      <ul className="triage-summary-list">
                        {splitSummaryTopics(request.interaction?.summary).map((topic) => (
                          <li key={topic}>{topic}</li>
                        ))}
                      </ul>
                    ) : (
                      <p>{extractMainText(request)}</p>
                    )}
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
                          <div className="patient-detail-actions">
                            <button type="button" className="psychologist-ghost-button" onClick={() => setNoteModalOpen(true)}>
                              Bloco de notas
                            </button>
                            <button type="button" className="psychologist-ghost-button" onClick={handlePrintPatientReport}>
                              Imprimir relatorio
                            </button>
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
                              <div className="patient-mini-list mood-card-list">
                                {patientDetail.moods.slice(0, 5).map((mood) => (
                                  <div key={mood.id} className="mood-mini-card">
                                    <div>
                                      <strong>{moodLabel(mood.valor)}</strong>
                                      <span>{formatDateTime(mood.criado_em)}</span>
                                    </div>
                                    <p>{isRawConversationText(mood.nota) ? 'Inferido a partir da conversa com a Lia.' : mood.nota || moodDescription(mood.valor)}</p>
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
                                    <div className="patient-chat-session-header">
                                      <div>
                                        <strong>Conversa com a Lia</strong>
                                        <span>{formatDateTime(interaction.created_at)}</span>
                                      </div>
                                      {interaction.topics.length ? (
                                        <span className="patient-chat-topic">{interaction.topics[0]}</span>
                                      ) : null}
                                    </div>
                                    {hasTranscript(interaction) ? (
                                      <div className="patient-chat-transcript">
                                        {getCleanTranscript(interaction).map((message, index) => (
                                          <div
                                            key={`${interaction.id ?? interaction.created_at}-${index}`}
                                            className={`patient-chat-message ${message.role}`}
                                          >
                                            <div className="patient-chat-avatar" aria-hidden="true">
                                              {message.role === 'assistant'
                                                ? 'L'
                                                : patientFirstName(patientDetail.user.nome).slice(0, 1).toUpperCase()}
                                            </div>
                                            <div className="patient-chat-bubble">
                                              <span>
                                                {message.role === 'assistant' ? 'Lia' : patientFirstName(patientDetail.user.nome)}
                                              </span>
                                              <p>{message.content}</p>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    ) : (
                                      <div className="patient-chat-transcript legacy">
                                        <div className="patient-chat-legacy-card">
                                          <span>Registro antigo</span>
                                          <strong>Transcricao completa indisponivel</strong>
                                          <p>
                                            Esta conversa foi salva antes do app guardar as falas completas. O resumo
                                            profissional ja aparece em “Relatorio da Lia”; novas conversas aparecerao aqui
                                            em formato de chat, com mensagens da Lia e do paciente.
                                          </p>
                                        </div>
                                      </div>
                                    )}
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

      {noteModalOpen && patientDetail ? (
        <div className="modal-backdrop" role="presentation">
          <section className="professional-modal" role="dialog" aria-modal="true" aria-label="Bloco de notas do paciente">
            <div className="professional-modal-header">
              <div>
                <span className="field-label">Bloco de notas</span>
                <h2>{patientDetail.user.nome}</h2>
                <p>Anotacoes privadas do profissional para esta solicitacao de triagem.</p>
              </div>
              <button type="button" className="psychologist-ghost-button" onClick={() => setNoteModalOpen(false)}>
                Fechar
              </button>
            </div>

            <textarea
              className="professional-note-area"
              value={noteDraft}
              onChange={(event) => setNoteDraft(event.target.value)}
              placeholder="Registre hipoteses de acolhimento, pontos para investigar na primeira consulta, observacoes e encaminhamentos combinados."
            />

            {noteFeedback ? <div className="alert success">{noteFeedback}</div> : null}

            <div className="professional-modal-actions">
              <button type="button" onClick={() => void handleSaveNote()} disabled={noteSaving}>
                {noteSaving ? 'Salvando...' : 'Salvar anotacao'}
              </button>
              <button type="button" className="psychologist-ghost-button" onClick={handleDownloadNote}>
                Baixar .txt
              </button>
              <button type="button" className="psychologist-ghost-button" onClick={handlePrintNote}>
                Imprimir notas
              </button>
              <button type="button" className="psychologist-ghost-button" onClick={handlePrintPatientReport}>
                Imprimir relatorio completo
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
