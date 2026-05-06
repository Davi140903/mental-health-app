import { startTransition, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { useAuth } from '../contexts/useAuth';

const LIA_DAILY_CHECKIN_PREFIX = 'mental-health-lia-daily-checkin';
const LIA_LIGHT_PROMPT_PREFIX = 'mental-health-lia-light-prompt';

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
];

function getDailyCheckInStorageKey(userId: string) {
  return `${LIA_DAILY_CHECKIN_PREFIX}:${userId}`;
}

function getLightPromptStorageKey(userId: string) {
  return `${LIA_LIGHT_PROMPT_PREFIX}:${userId}`;
}

function getTodayKey() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function getQuestionIndex(todayKey: string) {
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
  const todayKey = useMemo(() => getTodayKey(), []);
  const lightQuestion = useMemo(() => lightQuestions[getQuestionIndex(todayKey)], [todayKey]);
  const shouldSkipIntro = useMemo(() => {
    if (!user) {
      return false;
    }

    return localStorage.getItem(getDailyCheckInStorageKey(user.id)) === todayKey;
  }, [todayKey, user]);

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
    localStorage.setItem(getDailyCheckInStorageKey(user.id), todayKey);

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
      <Layout>
        <section className="section-card">
          <div className="empty-state">Abrindo sua conversa...</div>
        </section>
      </Layout>
    );
  }

  return (
    <Layout>
      <section className="section-card">
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
    </Layout>
  );
}
