import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { LiaSession, TriageRequest, TriageSlot } from '../types/app';

const LIA_SESSION_STORAGE_PREFIX = 'mental-health-lia-session';
const LIA_DRAFT_STORAGE_PREFIX = 'mental-health-lia-draft';
const LIA_LIGHT_PROMPT_PREFIX = 'mental-health-lia-light-prompt';

function getSessionStorageKey(userId: string) {
  return `${LIA_SESSION_STORAGE_PREFIX}:${userId}`;
}

function getDraftStorageKey(userId: string) {
  return `${LIA_DRAFT_STORAGE_PREFIX}:${userId}`;
}

function getLightPromptStorageKey(userId: string) {
  return `${LIA_LIGHT_PROMPT_PREFIX}:${userId}`;
}

function readStoredSession(storageKey: string) {
  const rawValue = localStorage.getItem(storageKey);
  if (!rawValue) {
    return null;
  }

  try {
    return JSON.parse(rawValue) as LiaSession;
  } catch {
    localStorage.removeItem(storageKey);
    return null;
  }
}

function getApiErrorMessage(error: unknown, fallbackMessage: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
  }

  return fallbackMessage;
}

function CompanionAvatar({ returning }: { returning: boolean }) {
  return (
    <div className="companion-card">
      <div className="companion-avatar" aria-hidden="true">
        <div className="companion-face">
          <span className="companion-eye left" />
          <span className="companion-eye right" />
          <span className="companion-mouth" />
        </div>
      </div>
      <div>
        <strong className="companion-name">Lia</strong>
        <p className="companion-copy">
          {returning ? 'A gente continua de onde parou.' : 'Um espaco simples pra voce falar um pouco.'}
        </p>
      </div>
    </div>
  );
}

export default function DashboardChat() {
  const { user } = useAuth();
  const [liaSession, setLiaSession] = useState<LiaSession | null>(null);
  const [liaError, setLiaError] = useState('');
  const [startingLia, setStartingLia] = useState(true);
  const [busy, setBusy] = useState(false);
  const [draftMessage, setDraftMessage] = useState('');
  const [triageRequest, setTriageRequest] = useState<TriageRequest | null>(null);
  const [triageSlots, setTriageSlots] = useState<TriageSlot[]>([]);
  const [triageBusy, setTriageBusy] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  const sessionStorageKey = user?.id ? getSessionStorageKey(user.id) : null;
  const draftStorageKey = user?.id ? getDraftStorageKey(user.id) : null;
  const lightPromptStorageKey = user?.id ? getLightPromptStorageKey(user.id) : null;

  const startConversation = useCallback(async () => {
    setStartingLia(true);
    setLiaError('');

    try {
      const response = await appService.startLiaConversation();
      const nextSession = response.session;
      if (lightPromptStorageKey) {
        const rawLightPrompt = sessionStorage.getItem(lightPromptStorageKey);
        if (rawLightPrompt) {
          try {
            const parsed = JSON.parse(rawLightPrompt) as { label?: string; value?: string };
            nextSession.memory.light_prompt_label = parsed.label ?? null;
            nextSession.memory.light_prompt_value = parsed.value ?? null;
          } catch {
            sessionStorage.removeItem(lightPromptStorageKey);
          }
        }
      }
      setLiaSession(nextSession);
    } catch (error) {
      setLiaError(getApiErrorMessage(error, 'Nao foi possivel iniciar a conversa agora.'));
    } finally {
      setStartingLia(false);
    }
  }, [lightPromptStorageKey]);

  useEffect(() => {
    if (!sessionStorageKey || !draftStorageKey) {
      return;
    }

    const storedSession = readStoredSession(sessionStorageKey);
    const storedDraft = localStorage.getItem(draftStorageKey) ?? '';

    setDraftMessage(storedDraft);

    if (storedSession && !storedSession.completed) {
      setLiaSession(storedSession);
      setStartingLia(false);
      return;
    }

    localStorage.removeItem(sessionStorageKey);
    void startConversation();
  }, [draftStorageKey, sessionStorageKey, startConversation]);

  useEffect(() => {
    if (!sessionStorageKey) {
      return;
    }

    if (!liaSession) {
      localStorage.removeItem(sessionStorageKey);
      return;
    }

    localStorage.setItem(sessionStorageKey, JSON.stringify(liaSession));
  }, [liaSession, sessionStorageKey]);

  useEffect(() => {
    if (!draftStorageKey) {
      return;
    }

    if (!draftMessage.trim()) {
      localStorage.removeItem(draftStorageKey);
      return;
    }

    localStorage.setItem(draftStorageKey, draftMessage);
  }, [draftMessage, draftStorageKey]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [liaSession?.transcript.length, busy]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedMessage = draftMessage.trim();
    if (!trimmedMessage || !liaSession || busy) {
      return;
    }

    setBusy(true);
    setLiaError('');
    setDraftMessage('');

    try {
      const response = await appService.sendLiaMessage(trimmedMessage, liaSession);
      setLiaSession(response.session);
    } catch (error) {
      setDraftMessage(trimmedMessage);
      setLiaError(getApiErrorMessage(error, 'Nao consegui ouvir sua mensagem agora.'));
    } finally {
      setBusy(false);
    }
  };

  const handleRestart = async () => {
    if (draftStorageKey) {
      localStorage.removeItem(draftStorageKey);
    }
    if (sessionStorageKey) {
      localStorage.removeItem(sessionStorageKey);
    }
    setDraftMessage('');
    setTriageRequest(null);
    setTriageSlots([]);
    await startConversation();
  };

  const loadTriageSlots = useCallback(async () => {
    const response = await appService.listTriageSlots();
    setTriageSlots(response);
  }, []);

  const handleCreateTriageRequest = async () => {
    if (!liaSession) {
      return;
    }

    setTriageBusy(true);
    setLiaError('');
    try {
      const request = await appService.createTriageRequest(liaSession.active_interaction_id ?? undefined);
      setTriageRequest(request);
      await loadTriageSlots();
    } catch (error) {
      setLiaError(getApiErrorMessage(error, 'Nao foi possivel iniciar o pedido de triagem agora.'));
    } finally {
      setTriageBusy(false);
    }
  };

  const handleScheduleTriage = async (slotId: number) => {
    if (!triageRequest) {
      return;
    }

    setTriageBusy(true);
    setLiaError('');
    try {
      const scheduled = await appService.scheduleTriage(triageRequest.id, slotId);
      setTriageRequest(scheduled);
      await loadTriageSlots();
    } catch (error) {
      setLiaError(getApiErrorMessage(error, 'Nao foi possivel agendar a triagem nesse horario.'));
    } finally {
      setTriageBusy(false);
    }
  };

  function formatDateTime(value: string) {
    return new Intl.DateTimeFormat('pt-BR', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
  }

  const transcript = liaSession?.transcript ?? [];
  const memory = liaSession?.memory;
  const isReturning = Boolean(memory && !memory.is_first_contact);
  const memorySummary = memory?.recent_summary ?? memory?.summary ?? null;
  const recentConversations = memory?.recent_conversations ?? [];
  const latestReport = memory?.latest_report ?? null;

  return (
    <Layout immersive>
      <div className="lia-home">
        <section className="section-card chat-panel chat-panel-immersive">
          <div className="companion-header companion-header-immersive">
            <CompanionAvatar returning={isReturning} />
            <div className="companion-text">
              <span className="pill">{isReturning ? 'De volta por aqui' : 'Comecando'}</span>
              <h2>{isReturning ? 'Bom te ver de novo' : 'Pode ficar a vontade'}</h2>
              <p>
                {isReturning
                  ? 'Se quiser, voce pode continuar de onde parou ou trazer outra coisa.'
                  : 'Pode comecar como for mais natural pra voce. A Lia acompanha a conversa a partir disso.'}
              </p>
            </div>
          </div>

          {memorySummary || memory?.topics.length ? (
            <div className="lia-memory-strip">
              {memorySummary ? <p>{memorySummary}</p> : null}
              {memory?.topics.length ? (
                <div className="lia-topic-list" aria-label="Temas que a Lia guarda com cuidado">
                  {memory.topics.map((topic) => (
                    <span key={topic} className="pill subtle">
                      {topic}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {recentConversations.length > 1 ? (
            <div className="lia-memory-strip">
              <p>Nas ultimas conversas, a Lia guardou estes pontos para continuar com mais contexto:</p>
              <div className="lia-topic-list" aria-label="Memoria breve das ultimas conversas">
                {recentConversations.slice(0, 3).map((item) => (
                  <span key={`${item.created_at}-${item.summary}`} className="pill subtle">
                    {item.summary}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <div className="chat-thread chat-thread-immersive" aria-live="polite">
            {transcript.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`chat-message ${message.role}`}>
                <div className="chat-bubble">{message.content}</div>
              </div>
            ))}

            {!startingLia && transcript.length === 0 ? (
              <div className="empty-state">A conversa vai aparecer aqui.</div>
            ) : null}

            <div ref={endRef} />
          </div>

          {liaError ? <div className="alert error">{liaError}</div> : null}

          <div className="chat-controls">
            {startingLia ? <div className="chat-waiting">A Lia esta chegando...</div> : null}

            {!startingLia && liaSession && !liaSession.completed ? (
              <form className="chat-composer" onSubmit={handleSubmit}>
                <p className="chat-hint">Escreva do seu jeito. A Lia segue com uma pergunta por vez.</p>
                <div className="chat-input-row">
                  <textarea
                    value={draftMessage}
                    onChange={(event) => setDraftMessage(event.target.value)}
                    placeholder="Ex.: ando muito pressionado e minha mente nao desliga"
                    disabled={busy}
                  />
                  <button type="submit" className="chat-submit" disabled={busy || !draftMessage.trim()}>
                    {busy ? 'Enviando...' : 'Enviar'}
                  </button>
                </div>
              </form>
            ) : null}

            {!startingLia && liaSession?.completed ? (
              <div className="chat-composer">
                <p className="chat-hint">A Lia ja guardou o essencial desta conversa. Se voce quiser, ainda pode continuar falando por aqui, ou pode parar sem pressa.</p>
                <div className="lia-memory-strip">
                  <p>
                    {triageRequest
                      ? 'Se voce quiser apoio profissional, pode seguir com a triagem. Se preferir, tambem pode continuar conversando mais um pouco antes disso.'
                      : 'Se por hoje ja foi o suficiente, tudo bem encerrar. E, se ainda houver algo importante, voce pode continuar o chat normalmente.'}
                  </p>
                  {latestReport ? <p className="panel-secondary-copy">{latestReport}</p> : null}
                </div>
                <div className="lia-post-chat-actions">
                  {!triageRequest ? (
                    <button type="button" className="secondary-button" onClick={() => void handleCreateTriageRequest()} disabled={triageBusy}>
                      {triageBusy ? 'Abrindo triagem...' : 'Encerrar e seguir para triagem'}
                    </button>
                  ) : null}

                  {triageRequest ? (
                    <div className="lia-memory-strip">
                      <p>
                        {triageRequest.status === 'scheduled'
                          ? `Triagem agendada com ${triageRequest.psychologist_name ?? 'psicologo'} em ${formatDateTime(triageRequest.scheduled_for ?? triageRequest.requested_at)}.`
                          : 'Seu pedido de triagem entrou na fila. Escolha um horario disponivel para concluir o agendamento.'}
                      </p>

                      {triageRequest.status !== 'scheduled' && triageSlots.length ? (
                        <div className="option-grid compact">
                          {triageSlots.slice(0, 6).map((slot) => (
                            <button
                              key={slot.id}
                              type="button"
                              className="choice"
                              onClick={() => void handleScheduleTriage(slot.id)}
                              disabled={triageBusy}
                            >
                              <strong>{slot.psychologist_name}</strong>
                              <span>{formatDateTime(slot.starts_at)}</span>
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <button type="button" className="chat-submit chat-restart" onClick={() => void handleRestart()}>
                  Continuar chat
                </button>
              </div>
            ) : null}
          </div>
        </section>

        <section className="lia-secondary-actions">
          <div className="lia-secondary-copy">
            <h3>O resto fica por perto</h3>
            <p>Quando fizer sentido, seus registros, conteudos e ajustes continuam acessiveis sem tirar a Lia do centro.</p>
          </div>

          <div className="lia-action-row">
            <Link to="/painel" className="quick-link-card">
              <strong>Painel</strong>
              <span>Ver um resumo breve das conversas, registros e sinais recentes.</span>
            </Link>
            <Link to="/humor" className="quick-link-card">
              <strong>Humor</strong>
              <span>Ver registros e adicionar um apontamento rapido.</span>
            </Link>
            <Link to="/contents" className="quick-link-card">
              <strong>Conteudos</strong>
              <span>Abrir leituras e praticas leves para o momento.</span>
            </Link>
            <Link to="/profile" className="quick-link-card">
              <strong>Perfil</strong>
              <span>Atualizar dados e revisar preferencias de cuidado.</span>
            </Link>
          </div>
        </section>

        <section className="section-card support-card support-card-inline">
          <h3>Se estiver muito pesado</h3>
          <p>Procure apoio profissional ou alguem de confianca. Em urgencia, busque ajuda imediata.</p>
        </section>
      </div>
    </Layout>
  );
}
