import { startTransition, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import { appService } from '../services/app';
import type { TriageRequest, TriageSlot } from '../types/app';
import {
  getCheckInCooldownExpiresAt,
  getCheckInCooldownStorageKey,
  getLightPromptStorageKey,
  hasActiveCheckInCooldown,
} from '../utils/checkin';

const lightQuestions = [
  {
    label: 'Primeiro ponto',
    question: 'O que voce quer conversar hoje?',
    options: [
      { label: 'Algo que esta pesando', value: 'algo que esta pesando' },
      { label: 'Uma duvida sobre mim', value: 'uma duvida sobre mim' },
      { label: 'Um assunto leve', value: 'um assunto leve' },
      { label: 'Ainda nao sei', value: 'ainda nao sei' },
    ],
  },
  {
    label: 'Ajuda de hoje',
    question: 'Qual ajuda faria mais sentido agora?',
    options: [
      { label: 'Organizar o que sinto', value: 'organizar o que sinto' },
      { label: 'Pensar no proximo passo', value: 'pensar no proximo passo' },
      { label: 'Conversar com calma', value: 'conversar com calma' },
      { label: 'Ir para triagem', value: 'ir para triagem' },
    ],
  },
  {
    label: 'Assuntos que importam',
    question: 'Quais topicos voce gostaria que a Lia lembrasse?',
    options: [
      { label: 'Trabalho ou estudos', value: 'trabalho ou estudos' },
      { label: 'Familia ou relacoes', value: 'familia ou relacoes' },
      { label: 'Sono e rotina', value: 'sono e rotina' },
      { label: 'Algo mais pessoal', value: 'algo mais pessoal' },
    ],
  },
  {
    label: 'Um assunto leve para lembrar',
    question: 'Qual desses assuntos combina mais com voce?',
    options: [
      { label: 'Musica', value: 'musica' },
      { label: 'Filmes e series', value: 'filmes e series' },
      { label: 'Esporte', value: 'esporte' },
      { label: 'Comida', value: 'comida' },
    ],
  },
  {
    label: 'Um assunto leve para lembrar',
    question: 'O que costuma te ajudar a distrair a cabeca?',
    options: [
      { label: 'Conversar com alguem', value: 'conversar com alguem' },
      { label: 'Ouvir musica', value: 'ouvir musica' },
      { label: 'Ver alguma coisa', value: 'ver alguma coisa' },
      { label: 'Ficar em silencio', value: 'ficar em silencio' },
    ],
  },
  {
    label: 'Uma entrada rapida',
    question: 'Se voce pudesse escolher uma pausa agora, qual seria?',
    options: [
      { label: 'Comida boa', value: 'comida boa' },
      { label: 'Descanso', value: 'descanso' },
      { label: 'Ar livre', value: 'ar livre' },
      { label: 'Musica', value: 'musica' },
    ],
  },
  {
    label: 'Um jeito de chegar',
    question: 'O que costuma te ajudar quando voce quer dar uma respirada?',
    options: [
      { label: 'Ficar sozinho', value: 'ficar sozinho' },
      { label: 'Ouvir alguma coisa', value: 'ouvir alguma coisa' },
      { label: 'Comer algo que gosta', value: 'comer algo que gosta' },
      { label: 'Mexer no celular', value: 'mexer no celular' },
    ],
  },
  {
    label: 'Para guardar para depois',
    question: 'Quais topicos voce costuma gostar de acompanhar?',
    options: [
      { label: 'Musica', value: 'musica' },
      { label: 'Esporte', value: 'esporte' },
      { label: 'Filmes e series', value: 'filmes e series' },
      { label: 'Comida', value: 'comida' },
    ],
  },
  {
    label: 'Uma pergunta simples',
    question: 'Se voce pudesse escolher uma companhia leve agora, qual seria?',
    options: [
      { label: 'Musica', value: 'musica' },
      { label: 'Silencio', value: 'silencio' },
      { label: 'Uma conversa tranquila', value: 'uma conversa tranquila' },
      { label: 'Algum video ou serie', value: 'algum video ou serie' },
    ],
  },
  {
    label: 'Pra quebrar o gelo',
    question: 'Qual dessas coisas mais combina com um momento seu?',
    options: [
      { label: 'Descanso', value: 'descanso' },
      { label: 'Ar livre', value: 'ar livre' },
      { label: 'Cafe ou lanche', value: 'cafe ou lanche' },
      { label: 'Assistir alguma coisa', value: 'assistir alguma coisa' },
    ],
  },
  {
    label: 'Uma pausa antes da conversa',
    question: 'Qual desses caminhos costuma te deixar um pouco mais leve?',
    options: [
      { label: 'Dormir ou deitar', value: 'dormir ou deitar' },
      { label: 'Ouvir musica', value: 'ouvir musica' },
      { label: 'Conversar com alguem', value: 'conversar com alguem' },
      { label: 'Ficar quieto', value: 'ficar quieto' },
    ],
  },
  {
    label: 'Um assunto para lembrar',
    question: 'Sobre qual assunto leve voce gostaria que a Lia lembrasse?',
    options: [
      { label: 'Musica', value: 'musica' },
      { label: 'Comida boa', value: 'comida boa' },
      { label: 'Ar livre', value: 'ar livre' },
      { label: 'Filme ou serie', value: 'filme ou serie' },
    ],
  },
  {
    label: 'Uma escolha leve',
    question: 'Quando voce quer se distrair um pouco, pra onde costuma ir primeiro?',
    options: [
      { label: 'Musica', value: 'musica' },
      { label: 'Video ou serie', value: 'video ou serie' },
      { label: 'Comida', value: 'comida' },
      { label: 'Silencio', value: 'silencio' },
    ],
  },
  {
    label: 'Uma preferencia rapida',
    question: 'Se tivesse que escolher uma dessas agora, qual seria?',
    options: [
      { label: 'Descanso', value: 'descanso' },
      { label: 'Musica', value: 'musica' },
      { label: 'Conversa', value: 'conversa' },
      { label: 'Alguma distracao', value: 'alguma distracao' },
    ],
  },
];

function getQuestionIndex() {
  const todayKey = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
  const digits = todayKey.replaceAll('-', '');
  const total = digits.split('').reduce((sum, char) => sum + Number(char || 0), 0);
  return total % lightQuestions.length;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [otherSelected, setOtherSelected] = useState(false);
  const [otherValue, setOtherValue] = useState('');
  const [triageRequest, setTriageRequest] = useState<TriageRequest | null>(null);
  const [triageSlots, setTriageSlots] = useState<TriageSlot[]>([]);
  const [triageBusy, setTriageBusy] = useState(false);
  const [triageError, setTriageError] = useState('');
  const lightQuestion = useMemo(() => lightQuestions[getQuestionIndex()], []);
  const shouldSkipIntro = useMemo(() => {
    if (!user) {
      return false;
    }

    return hasActiveCheckInCooldown(user.id);
  }, [user]);

  useEffect(() => {
    if (shouldSkipIntro) {
      startTransition(() => {
        navigate('/lia', { replace: true });
      });
    }
  }, [navigate, shouldSkipIntro]);

  const completeIntro = (label: string, value: string) => {
    if (!user) {
      return;
    }

    setSelectedOption(label);
    sessionStorage.setItem(
      getLightPromptStorageKey(user.id),
      JSON.stringify({
        label: lightQuestion.label,
        value,
      }),
    );
    localStorage.setItem(getCheckInCooldownStorageKey(user.id), getCheckInCooldownExpiresAt());

    startTransition(() => {
      navigate('/lia');
    });
  };

  const handleChooseOption = (label: string, value: string) => {
    setOtherSelected(false);
    setOtherValue('');
    completeIntro(label, value);
  };

  const handleChooseOther = () => {
    setSelectedOption('Outro');
    setOtherSelected(true);
  };

  const handleSubmitOther = () => {
    const trimmed = otherValue.trim();
    if (!trimmed) {
      return;
    }
    completeIntro('Outro', trimmed);
  };

  const handleDirectTriage = async () => {
    setTriageBusy(true);
    setTriageError('');

    try {
      const request = await appService.createTriageRequest();
      const slots = await appService.listTriageSlots();
      setTriageRequest(request);
      setTriageSlots(slots);
    } catch {
      setTriageError('Nao foi possivel abrir a triagem agora. Voce ainda pode conversar com a Lia.');
    } finally {
      setTriageBusy(false);
    }
  };

  const handleScheduleTriage = async (slotId: number) => {
    if (!triageRequest || !user) {
      return;
    }

    setTriageBusy(true);
    setTriageError('');

    try {
      const scheduled = await appService.scheduleTriage(triageRequest.id, slotId);
      setTriageRequest(scheduled);
      localStorage.setItem(getCheckInCooldownStorageKey(user.id), getCheckInCooldownExpiresAt());
    } catch {
      setTriageError('Nao foi possivel agendar esse horario agora.');
    } finally {
      setTriageBusy(false);
    }
  };

  if (shouldSkipIntro) {
    return (
      <div className="auth-page">
        <section className="section-card auth-card auth-card-wide">
          <div className="empty-state">Abrindo sua conversa...</div>
        </section>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <section className="section-card auth-card auth-card-wide">
        <div className="support-card-inline direct-triage-card">
          <h3>Se hoje estiver pesado demais para conversar, tudo bem.</h3>
          <p>Voce pode ir direto para a triagem com um profissional, sem precisar conversar com a Lia agora.</p>

          {!triageRequest ? (
            <button type="button" className="secondary-button" onClick={() => void handleDirectTriage()} disabled={triageBusy}>
              {triageBusy ? 'Abrindo triagem...' : 'Ir direto para triagem'}
            </button>
          ) : null}

          {triageRequest ? (
            <div className="summary-block calm-card">
              <p>
                {triageRequest.status === 'scheduled'
                  ? `Triagem agendada com ${triageRequest.psychologist_name ?? 'psicologo'} em ${formatDateTime(
                      triageRequest.scheduled_for ?? triageRequest.requested_at,
                    )}.`
                  : 'Escolha um horario disponivel para concluir sua triagem.'}
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

              {triageRequest.status !== 'scheduled' && !triageSlots.length ? (
                <p className="chat-hint">No momento nao ha horarios disponiveis. Tente novamente mais tarde.</p>
              ) : null}
            </div>
          ) : null}

          {triageError ? <div className="alert error">{triageError}</div> : null}
        </div>

        <div className="companion-header">
          <div className="companion-text">
            <span className="pill">{lightQuestion.label}</span>
            <h2>{lightQuestion.question}</h2>
            <p>Isso ajuda a Lia a puxar a conversa de um jeito mais natural, se fizer sentido depois.</p>
          </div>
        </div>

        <div className="choice-cluster">
          {lightQuestion.options.map((option) => (
            <button
              key={option.label}
              type="button"
              className={selectedOption === option.label ? 'chat-choice' : 'chat-choice soft'}
              onClick={() => handleChooseOption(option.label, option.value)}
            >
              {option.label}
            </button>
          ))}
          <button
            type="button"
            className={selectedOption === 'Outro' ? 'chat-choice' : 'chat-choice soft'}
            onClick={handleChooseOther}
          >
            Outro
          </button>
        </div>

        {otherSelected ? (
          <div className="chat-note-composer">
            <textarea
              value={otherValue}
              onChange={(event) => setOtherValue(event.target.value)}
              placeholder="Escreve do seu jeito"
              rows={3}
            />
            <div className="chat-note-actions">
              <button type="button" onClick={handleSubmitOther} disabled={!otherValue.trim()}>
                Continuar
              </button>
            </div>
          </div>
        ) : null}

        <p className="chat-hint">Depois disso, voce vai direto para a conversa e pode falar do jeito que quiser.</p>
      </section>
    </div>
  );
}
