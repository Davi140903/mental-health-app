import { type FormEvent, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { LiaSession } from '../types/app';

const LIA_SESSION_STORAGE_PREFIX = 'mental-health-lia-session';
const LIA_DRAFT_STORAGE_PREFIX = 'mental-health-lia-draft';

function getSessionStorageKey(userId: string) {
  return `${LIA_SESSION_STORAGE_PREFIX}:${userId}`;
}

function getDraftStorageKey(userId: string) {
  return `${LIA_DRAFT_STORAGE_PREFIX}:${userId}`;
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
          {returning ? 'Continuamos de onde for melhor para voce.' : 'Uma conversa acolhedora, no seu ritmo.'}
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
  const endRef = useRef<HTMLDivElement | null>(null);

  const sessionStorageKey = user?.id ? getSessionStorageKey(user.id) : null;
  const draftStorageKey = user?.id ? getDraftStorageKey(user.id) : null;

  const startConversation = async () => {
    setStartingLia(true);
    setLiaError('');

    try {
      const response = await appService.startLiaConversation();
      setLiaSession(response.session);
    } catch (error) {
      setLiaError(getApiErrorMessage(error, 'Nao foi possivel iniciar a conversa agora.'));
    } finally {
      setStartingLia(false);
    }
  };

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
  }, [sessionStorageKey, draftStorageKey]);

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
    await startConversation();
  };

  const transcript = liaSession?.transcript ?? [];
  const memory = liaSession?.memory;
  const isReturning = Boolean(memory && !memory.is_first_contact);
  const memorySummary = memory?.recent_summary ?? memory?.summary ?? null;

  return (
    <Layout immersive>
      <div className="lia-home">
        <section className="section-card chat-panel chat-panel-immersive">
          <div className="companion-header companion-header-immersive">
            <CompanionAvatar returning={isReturning} />
            <div className="companion-text">
              <span className="pill">{isReturning ? 'Retomada com contexto' : 'Primeira conversa'}</span>
              <h2>{isReturning ? 'Seguimos do seu jeito' : 'Vamos com calma'}</h2>
              <p>
                {isReturning
                  ? 'A Lia guarda so o contexto importante, para voce nao precisar recomecar do zero.'
                  : 'Depois do login, a Lia vira seu ponto de partida e vai te conhecendo aos poucos.'}
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
                <p className="chat-hint">Esse check-in foi concluido. Se quiser, a Lia pode recomecar com voce.</p>
                <button type="button" className="chat-submit chat-restart" onClick={() => void handleRestart()}>
                  Novo check-in
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
