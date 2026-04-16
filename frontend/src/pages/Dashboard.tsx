import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type {
  DashboardData,
  MoodHistoryPoint,
  QuestionnaireKind,
  QuestionnaireResult,
  Recommendation,
} from '../types/app';

type MessageRole = 'assistant' | 'user';

interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
}

type ConversationAction =
  | { type: 'choose-path' }
  | { type: 'choose-mood' }
  | { type: 'choose-mood-note'; moodValue: number; moodLabel: string }
  | { type: 'write-mood-note'; moodValue: number; moodLabel: string }
  | { type: 'question'; kind: QuestionnaireKind; index: number; answers: number[] }
  | { type: 'grounding'; step: number }
  | { type: 'follow-up' }
  | { type: 'restart' };

const moodLabels: Record<number, string> = {
  1: 'Muito baixo',
  2: 'Baixo',
  3: 'Neutro',
  4: 'Bom',
  5: 'Muito bom',
};

const priorityLabels: Record<Recommendation['prioridade'], string> = {
  baixa: 'Baixa',
  media: 'Media',
  alta: 'Alta',
};

const moodChoices = [
  { value: 1, label: 'Muito baixo' },
  { value: 2, label: 'Baixo' },
  { value: 3, label: 'Neutro' },
  { value: 4, label: 'Bom' },
  { value: 5, label: 'Muito bom' },
];

const answerOptions = [
  { value: 0, label: 'Nunca' },
  { value: 1, label: 'Alguns dias' },
  { value: 2, label: 'Metade dos dias' },
  { value: 3, label: 'Quase sempre' },
];

const groundingSteps = [
  'Olhe ao redor e encontre 3 coisas que voce consegue ver.',
  'Agora note 2 sons perto de voce.',
  'Por fim, solte os ombros e faca 4 respiracoes lentas, no seu tempo.',
];

const questionnaireFlows: Record<
  QuestionnaireKind,
  { label: string; intro: string; questions: string[] }
> = {
  phq9: {
    label: 'Quero entender meu humor',
    intro: 'Tudo bem. Vou te fazer algumas perguntas curtas sobre as ultimas duas semanas.',
    questions: [
      'Voce teve pouco interesse ou prazer em fazer as coisas?',
      'Voce se sentiu para baixo ou sem esperanca?',
      'Teve dificuldade para dormir bem ou dormiu demais?',
      'Se sentiu cansado ou com pouca energia?',
      'Percebeu mudancas no apetite?',
      'Se sentiu mal consigo mesmo?',
      'Teve dificuldade para se concentrar?',
      'Se sentiu muito lento ou inquieto?',
      'Pensou que seria melhor nao estar aqui ou em se machucar?',
    ],
  },
  gad7: {
    label: 'Quero falar de ansiedade',
    intro: 'Certo. Vou seguir com perguntas curtas sobre as ultimas duas semanas.',
    questions: [
      'Voce se sentiu nervoso, ansioso ou muito tenso?',
      'Teve dificuldade para parar ou controlar as preocupacoes?',
      'Se preocupou demais com varias coisas?',
      'Teve dificuldade para relaxar?',
      'Ficou inquieto a ponto de ser dificil parar?',
      'Ficou irritado ou se incomodou com facilidade?',
      'Sentiu medo de que algo ruim pudesse acontecer?',
    ],
  },
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function getFirstName(name?: string | null) {
  return name?.trim().split(' ')[0] || 'voce';
}

function getMoodSupport(value: number) {
  if (value <= 2) {
    return 'Obrigada por me contar. Vamos seguir com leveza e um passo de cada vez.';
  }

  if (value === 3) {
    return 'Entendi. Mesmo no meio do caminho, vale observar o que ajuda voce a se sentir um pouco melhor.';
  }

  return 'Que bom perceber um momento um pouco mais leve. Vale guardar o que esta ajudando hoje.';
}

function getResultSupport(result: QuestionnaireResult) {
  if (result.tipo === 'phq9') {
    if (result.respostas[8] > 0) {
      return 'Percebi um sinal sensivel na sua ultima resposta. Se houver risco agora, procure ajuda profissional ou um servico de urgencia imediatamente.';
    }

    if (result.pontuacao >= 15) {
      return 'Os sinais parecem mais intensos. Se fizer sentido, busque apoio profissional e de pessoas de confianca.';
    }
    if (result.pontuacao >= 10) {
      return 'Existem sinais que merecem atencao e cuidado nas proximas semanas.';
    }
    return 'Neste momento, os sinais parecem mais leves, mas voce pode continuar acompanhando.';
  }

  if (result.pontuacao >= 15) {
    return 'A ansiedade parece estar pesando bastante agora. Vale reduzir exigencias e buscar apoio.';
  }
  if (result.pontuacao >= 10) {
    return 'Existem sinais de ansiedade que merecem cuidado e pausas ao longo dos dias.';
  }
  return 'Neste momento, os sinais parecem mais leves, mas voce pode continuar observando.';
}

function getSuggestedContent(
  dashboard: DashboardData | null,
  focusKind: QuestionnaireKind | null,
) {
  if (!dashboard) {
    return null;
  }

  if (focusKind) {
    const matched = dashboard.conteudos_em_destaque.find((item) => item.questionario_tipo === focusKind);
    if (matched) {
      return matched;
    }
  }

  return dashboard.conteudos_em_destaque[0] ?? null;
}

function HistoryChart({ points }: { points: MoodHistoryPoint[] }) {
  const visiblePoints = points.slice(-5);

  if (!visiblePoints.length) {
    return <div className="empty-state">Ainda nao ha registros suficientes.</div>;
  }

  return (
    <div className="chart-bars compact-chart" aria-label="Historico recente de humor">
      {visiblePoints.map((point) => (
        <div key={`${point.data}-${point.valor}`} className="chart-bar-item">
          <div className="chart-bar-track">
            <div className="chart-bar-fill" style={{ height: `${point.valor * 20}%` }} />
          </div>
          <span>{point.data}</span>
        </div>
      ))}
    </div>
  );
}

function CompanionAvatar() {
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
        <p className="companion-copy">Uma conversa curta, no seu ritmo.</p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [action, setAction] = useState<ConversationAction>({ type: 'choose-path' });
  const [draftNote, setDraftNote] = useState('');
  const [chatError, setChatError] = useState('');
  const [busy, setBusy] = useState(false);
  const [focusKind, setFocusKind] = useState<QuestionnaireKind | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const messageCounter = useRef(0);
  const greetedUser = useRef<string | null>(null);

  const createMessage = (role: MessageRole, text: string): ChatMessage => {
    const id = `message-${messageCounter.current}`;
    messageCounter.current += 1;
    return { id, role, text };
  };

  const appendMessages = (nextMessages: ChatMessage[]) => {
    setMessages((current) => [...current, ...nextMessages]);
  };

  const refreshDashboard = async () => {
    try {
      const response = await appService.getDashboard();
      setDashboard(response);
      setError('');
    } catch {
      setError('Nao foi possivel carregar seus dados agora.');
    }
  };

  const resetConversation = () => {
    messageCounter.current = 0;
    setMessages([
      createMessage('assistant', `Oi, ${getFirstName(user?.nome)}. Eu sou a Lia.`),
      createMessage('assistant', 'Posso ficar com voce por alguns minutos. O que faria mais sentido agora?'),
    ]);
    setAction({ type: 'choose-path' });
    setDraftNote('');
    setChatError('');
    setBusy(false);
    setFocusKind(null);
  };

  useEffect(() => {
    let active = true;

    const loadDashboard = async () => {
      try {
        const response = await appService.getDashboard();
        if (active) {
          setDashboard(response);
        }
      } catch {
        if (active) {
          setError('Nao foi possivel carregar seus dados agora.');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadDashboard();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const currentName = user?.nome ?? '__guest__';
    if (greetedUser.current === currentName) {
      return;
    }

    greetedUser.current = currentName;
    messageCounter.current = 0;
    const welcomeMessages: ChatMessage[] = [
      {
        id: `message-${messageCounter.current++}`,
        role: 'assistant',
        text: `Oi, ${getFirstName(user?.nome)}. Eu sou a Lia.`,
      },
      {
        id: `message-${messageCounter.current++}`,
        role: 'assistant',
        text: 'Posso ficar com voce por alguns minutos. O que faria mais sentido agora?',
      },
    ];
    setMessages([
      ...welcomeMessages,
    ]);
    setAction({ type: 'choose-path' });
    setDraftNote('');
    setChatError('');
    setBusy(false);
    setFocusKind(null);
  }, [user?.nome]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, action, busy]);

  const handleStartMood = () => {
    setChatError('');
    setFocusKind(null);
    appendMessages([
      createMessage('user', 'Quero um check-in rapido'),
      createMessage('assistant', 'Vamos com calma. Como voce esta agora?'),
    ]);
    setAction({ type: 'choose-mood' });
  };

  const handleStartQuestionnaire = (kind: QuestionnaireKind) => {
    setChatError('');
    setFocusKind(kind);
    const flow = questionnaireFlows[kind];
    appendMessages([
      createMessage('user', flow.label),
      createMessage('assistant', flow.intro),
      createMessage('assistant', flow.questions[0]),
    ]);
    setAction({ type: 'question', kind, index: 0, answers: [] });
  };

  const handleStartGrounding = () => {
    setChatError('');
    setFocusKind(null);
    appendMessages([
      createMessage('user', 'Preciso me acalmar agora'),
      createMessage('assistant', 'Tudo bem. Vamos reduzir o ritmo juntas.'),
      createMessage('assistant', groundingSteps[0]),
    ]);
    setAction({ type: 'grounding', step: 0 });
  };

  const handleMoodSelected = (value: number, label: string) => {
    setChatError('');
    setDraftNote('');
    appendMessages([
      createMessage('user', label),
      createMessage('assistant', 'Quer registrar uma observacao ou prefere salvar assim?'),
    ]);
    setAction({ type: 'choose-mood-note', moodValue: value, moodLabel: label });
  };

  const handleMoodNoteDecision = (shouldWrite: boolean) => {
    if (action.type !== 'choose-mood-note') {
      return;
    }

    setChatError('');

    if (shouldWrite) {
      appendMessages([
        createMessage('user', 'Quero adicionar uma observacao'),
        createMessage('assistant', 'Escreva em uma frase o que esta pesando ou ajudando agora.'),
      ]);
      setAction({
        type: 'write-mood-note',
        moodValue: action.moodValue,
        moodLabel: action.moodLabel,
      });
      return;
    }

    appendMessages([createMessage('user', 'Salvar assim')]);
    void handleSaveMood(action.moodValue, action.moodLabel, '');
  };

  const handleSubmitMoodNote = () => {
    if (action.type !== 'write-mood-note') {
      return;
    }

    const cleanNote = draftNote.trim();

    if (cleanNote) {
      appendMessages([createMessage('user', cleanNote)]);
    }

    void handleSaveMood(action.moodValue, action.moodLabel, cleanNote);
  };

  const handleSkipMoodNote = () => {
    if (action.type !== 'write-mood-note') {
      return;
    }

    appendMessages([createMessage('user', 'Prefiro pular')]);
    void handleSaveMood(action.moodValue, action.moodLabel, '');
  };

  const handleSaveMood = async (value: number, label: string, note: string) => {
    setBusy(true);
    setChatError('');

    try {
      await appService.createMood({
        valor: value,
        nota: note || undefined,
      });

      await refreshDashboard();

      const completionMessages = [
        createMessage('assistant', `Pronto. Registrei seu momento como "${label.toLowerCase()}".`),
        createMessage('assistant', getMoodSupport(value)),
      ];

      appendMessages(completionMessages);
      setDraftNote('');
      setAction({ type: 'follow-up' });
    } catch {
      setChatError('Nao consegui salvar esse registro agora.');
      setAction({ type: 'restart' });
    } finally {
      setBusy(false);
    }
  };

  const handleQuestionAnswer = async (value: number, label: string) => {
    if (action.type !== 'question') {
      return;
    }

    const flow = questionnaireFlows[action.kind];
    const nextAnswers = [...action.answers, value];

    appendMessages([createMessage('user', label)]);

    if (action.index < flow.questions.length - 1) {
      appendMessages([createMessage('assistant', flow.questions[action.index + 1])]);
      setAction({
        type: 'question',
        kind: action.kind,
        index: action.index + 1,
        answers: nextAnswers,
      });
      return;
    }

    setBusy(true);
    setChatError('');

    try {
      const result = await appService.submitQuestionnaire(action.kind, {
        respostas: nextAnswers,
      });
      await refreshDashboard();
      appendMessages([
        createMessage(
          'assistant',
          `Obrigada por responder. Seu resultado ficou em ${result.pontuacao} e foi classificado como ${result.classificacao.toLowerCase()}.`,
        ),
        createMessage('assistant', getResultSupport(result)),
      ]);
      setAction({ type: 'follow-up' });
    } catch {
      setChatError('Nao consegui salvar esse resultado agora.');
      setAction({ type: 'restart' });
    } finally {
      setBusy(false);
    }
  };

  const handleGroundingNext = () => {
    if (action.type !== 'grounding') {
      return;
    }

    const nextStep = action.step + 1;
    appendMessages([createMessage('user', 'Pronto')]);

    if (nextStep < groundingSteps.length) {
      appendMessages([createMessage('assistant', groundingSteps[nextStep])]);
      setAction({ type: 'grounding', step: nextStep });
      return;
    }

    appendMessages([
      createMessage('assistant', 'Obrigada por fazer isso comigo.'),
      createMessage('assistant', 'Se fizer sentido, me diga como voce esta agora.'),
    ]);
    setAction({ type: 'choose-mood' });
  };

  const handlePauseConversation = () => {
    appendMessages([
      createMessage('user', 'Quero parar por agora'),
      createMessage('assistant', 'Tudo bem. Quando voce quiser, podemos recomecar daqui com calma.'),
    ]);
    setAction({ type: 'restart' });
  };

  const renderControls = () => {
    if (busy) {
      return <div className="chat-waiting">Estou organizando isso para voce...</div>;
    }

    switch (action.type) {
      case 'choose-path':
        return (
          <div className="choice-cluster">
            <button type="button" className="chat-choice" onClick={handleStartMood}>
              Check-in rapido
            </button>
            <button type="button" className="chat-choice" onClick={() => handleStartQuestionnaire('gad7')}>
              Ansiedade
            </button>
            <button type="button" className="chat-choice" onClick={() => handleStartQuestionnaire('phq9')}>
              Humor nas ultimas semanas
            </button>
            <button type="button" className="chat-choice soft" onClick={handleStartGrounding}>
              Preciso me acalmar
            </button>
          </div>
        );
      case 'choose-mood':
        return (
          <div className="choice-cluster">
            {moodChoices.map((choice) => (
              <button
                key={choice.value}
                type="button"
                className="chat-choice"
                onClick={() => handleMoodSelected(choice.value, choice.label)}
              >
                {choice.label}
              </button>
            ))}
          </div>
        );
      case 'choose-mood-note':
        return (
          <div className="choice-cluster">
            <button type="button" className="chat-choice" onClick={() => handleMoodNoteDecision(true)}>
              Adicionar observacao
            </button>
            <button type="button" className="chat-choice soft" onClick={() => handleMoodNoteDecision(false)}>
              Salvar assim
            </button>
          </div>
        );
      case 'write-mood-note':
        return (
          <div className="chat-note-composer">
            <textarea
              value={draftNote}
              onChange={(event) => setDraftNote(event.target.value)}
              placeholder="Se quiser, escreva algo curto sobre este momento."
            />
            <div className="chat-note-actions">
              <button
                type="button"
                onClick={handleSubmitMoodNote}
              >
                Salvar
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={handleSkipMoodNote}
              >
                Pular
              </button>
            </div>
          </div>
        );
      case 'question':
        return (
          <div className="choice-cluster">
            {answerOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className="chat-choice"
                onClick={() => void handleQuestionAnswer(option.value, option.label)}
              >
                {option.label}
              </button>
            ))}
          </div>
        );
      case 'grounding':
        return (
          <div className="choice-cluster">
            <button type="button" className="chat-choice" onClick={handleGroundingNext}>
              Ja fiz
            </button>
          </div>
        );
      case 'follow-up':
        return (
          <div className="choice-cluster">
            <button type="button" className="chat-choice" onClick={handleStartMood}>
              Novo check-in
            </button>
            <button type="button" className="chat-choice" onClick={() => handleStartQuestionnaire('gad7')}>
              Ansiedade
            </button>
            <button type="button" className="chat-choice" onClick={() => handleStartQuestionnaire('phq9')}>
              Humor
            </button>
            <button type="button" className="chat-choice soft" onClick={handlePauseConversation}>
              Parar por agora
            </button>
          </div>
        );
      case 'restart':
        return (
          <div className="choice-cluster">
            <button type="button" className="chat-choice" onClick={resetConversation}>
              Recomecar conversa
            </button>
          </div>
        );
      default:
        return null;
    }
  };

  const featuredContent = getSuggestedContent(dashboard, focusKind);
  const recentResult = dashboard?.ultimos_questionarios[0] ?? null;
  const nextRecommendation = dashboard?.recomendacoes[0] ?? null;

  return (
    <Layout>
      <div className="welcome-layout">
        <section className="section-card chat-panel">
          <div className="companion-header">
            <CompanionAvatar />
            <div className="companion-text">
              <span className="pill">Acolhimento guiado</span>
              <h2>Um passo de cada vez</h2>
              <p>Escolha um caminho e siga no seu ritmo.</p>
            </div>
          </div>

          <div className="chat-thread" aria-live="polite">
            {messages.map((message) => (
              <div key={message.id} className={`chat-message ${message.role}`}>
                <div className="chat-bubble">
                  {message.text}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>

          {chatError ? <div className="alert error">{chatError}</div> : null}

          <div className="chat-controls">{renderControls()}</div>
        </section>

        <aside className="summary-stack">
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Seu momento recente</h3>
              </div>
            </div>

            {loading ? <div className="empty-state">Carregando...</div> : null}
            {error ? <div className="alert error">{error}</div> : null}

            {dashboard?.ultimo_humor ? (
              <div className="focus-card">
                <div className="focus-meta">
                  <span className="stat-label">Ultimo humor</span>
                  <strong className="stat-value small">{moodLabels[dashboard.ultimo_humor.valor]}</strong>
                  <p>{formatDate(dashboard.ultimo_humor.criado_em)}</p>
                </div>
                {dashboard.ultimo_humor.nota ? <p className="quiet-note">{dashboard.ultimo_humor.nota}</p> : null}
              </div>
            ) : (
              !loading && <div className="empty-state">Seu primeiro registro pode comecar pela conversa ao lado.</div>
            )}

            {dashboard ? <HistoryChart points={dashboard.historico_humor} /> : null}
          </article>

          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Um passo leve</h3>
              </div>
            </div>

            {nextRecommendation ? (
              <div className="recommendation-card calm-card">
                <div className="recommendation-header">
                  <strong>{nextRecommendation.titulo}</strong>
                  <span className={`priority-tag ${nextRecommendation.prioridade}`}>
                    {priorityLabels[nextRecommendation.prioridade]}
                  </span>
                </div>
                <p>{nextRecommendation.descricao}</p>
              </div>
            ) : (
              <div className="empty-state">As orientacoes aparecem conforme voce usa o app.</div>
            )}

            {recentResult ? (
              <div className="summary-block">
                <span className="stat-label">Ultimo resultado</span>
                <strong>
                  {recentResult.tipo.toUpperCase()} • {recentResult.pontuacao}
                </strong>
                <p>{recentResult.classificacao}</p>
              </div>
            ) : null}
          </article>

          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Leitura sugerida</h3>
              </div>
              <Link to="/contents" className="inline-link">
                Ver mais
              </Link>
            </div>

            {featuredContent ? (
              <article className="content-card compact-card calm-card">
                <span className="pill">{featuredContent.categoria}</span>
                <h4>{featuredContent.titulo}</h4>
                <p>{featuredContent.resumo}</p>
              </article>
            ) : (
              <div className="empty-state">Os conteudos aparecem aqui quando estiverem disponiveis.</div>
            )}
          </article>

          <article className="section-card support-card">
            <h3>Se estiver muito pesado</h3>
            <p>Procure apoio profissional ou alguem de confianca. Em urgencia, busque ajuda imediata.</p>
          </article>
        </aside>
      </div>
    </Layout>
  );
}
