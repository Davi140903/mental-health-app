import { startTransition, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import {
  getCheckInCooldownExpiresAt,
  getCheckInCooldownStorageKey,
  getLightPromptStorageKey,
  hasActiveCheckInCooldown,
} from '../utils/checkin';

const lightQuestions = [
  {
    label: 'Uma curiosidade pra comecar',
    question: 'Qual dessas coisas voce curte mais?',
    options: [
      { label: 'Musica', value: 'musica' },
      { label: 'Filmes e series', value: 'filmes e series' },
      { label: 'Esporte', value: 'esporte' },
      { label: 'Comida', value: 'comida' },
    ],
  },
  {
    label: 'Um assunto leve pra guardar',
    question: 'Qual dessas coisas mais te ajuda a distrair a cabeca?',
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
    question: 'Qual dessas coisas combina mais com voce quando quer dar uma respirada?',
    options: [
      { label: 'Ficar sozinho', value: 'ficar sozinho' },
      { label: 'Ouvir alguma coisa', value: 'ouvir alguma coisa' },
      { label: 'Comer algo que gosta', value: 'comer algo que gosta' },
      { label: 'Mexer no celular', value: 'mexer no celular' },
    ],
  },
  {
    label: 'Pra guardar pra depois',
    question: 'Qual desses assuntos costuma te prender mais facil?',
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
    label: 'So pra comecar',
    question: 'Qual dessas coisas voce escolheria agora sem pensar muito?',
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
      { label: 'Alguma distração', value: 'alguma distracao' },
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

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [otherSelected, setOtherSelected] = useState(false);
  const [otherValue, setOtherValue] = useState('');
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
      })
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
        <div className="companion-header">
          <div className="companion-text">
            <span className="pill">{lightQuestion.label}</span>
            <h2>{lightQuestion.question}</h2>
            <p>Isso e so uma entrada leve. Mais tarde, a Lia pode puxar esse assunto de um jeito natural.</p>
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

        <p className="chat-hint">Depois disso, voce vai direto pra conversa e pode falar do jeito que quiser.</p>
      </section>
    </div>
  );
}
