import { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import { appService } from '../services/app';
import type { QuestionnaireKind, QuestionnaireResult } from '../types/app';

interface QuestionnairePageProps {
  kind: QuestionnaireKind;
  title: string;
  description: string;
  questions: string[];
}

const answerOptions = [
  { label: 'Nunca', value: 0 },
  { label: 'Varios dias', value: 1 },
  { label: 'Mais da metade dos dias', value: 2 },
  { label: 'Quase todos os dias', value: 3 },
];

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export default function QuestionnairePage({ kind, title, description, questions }: QuestionnairePageProps) {
  const [answers, setAnswers] = useState<Array<number | null>>(() => Array.from({ length: questions.length }, () => null));
  const [history, setHistory] = useState<QuestionnaireResult[]>([]);
  const [result, setResult] = useState<QuestionnaireResult | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setAnswers(Array.from({ length: questions.length }, () => null));
    setResult(null);
  }, [questions.length, kind]);

  useEffect(() => {
    let active = true;

    const loadHistory = async () => {
      try {
        const response = await appService.listQuestionnaireResults(kind);
        if (active) {
          setHistory(response);
        }
      } catch {
        if (active) {
          setError('Nao foi possivel carregar o historico desse questionario.');
        }
      } finally {
        if (active) {
          setLoadingHistory(false);
        }
      }
    };

    void loadHistory();

    return () => {
      active = false;
    };
  }, [kind]);

  const answeredCount = answers.filter((answer) => answer !== null).length;
  const score = answers.reduce<number>((total, value) => total + (value ?? 0), 0);
  const isComplete = answeredCount === questions.length;

  const handleAnswer = (questionIndex: number, value: number) => {
    setAnswers((current) => current.map((answer, index) => (index === questionIndex ? value : answer)));
  };

  const handleSubmit = async () => {
    setError('');

    if (!isComplete) {
      setError('Responda todas as perguntas antes de concluir.');
      return;
    }

    setSubmitting(true);
    try {
      const createdResult = await appService.submitQuestionnaire(kind, {
        respostas: answers.map((answer) => answer ?? 0),
      });
      setResult(createdResult);
      setHistory((current) => [createdResult, ...current]);
    } catch {
      setError('Nao foi possivel salvar suas respostas.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout>
      <section className="split-layout questionnaire-layout">
        <article className="section-card wide-panel">
          <div className="section-heading">
            <div>
              <h2>{title}</h2>
            </div>
            <span className="pill">Respondidas: {answeredCount}/{questions.length}</span>
          </div>

          <p>{description}</p>

          <div className="question-list">
            {questions.map((question, index) => (
              <article key={question} className="question-card">
                <h3>
                  {index + 1}. {question}
                </h3>
                <div className="option-grid compact">
                  {answerOptions.map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      className={answers[index] === option.value ? 'choice active' : 'choice'}
                      onClick={() => handleAnswer(index, option.value)}
                    >
                      <strong>{option.label}</strong>
                    </button>
                  ))}
                </div>
              </article>
            ))}
          </div>

          <div className="submission-row">
            <div>
              <span className="stat-label">Pontuacao parcial</span>
              <strong className="stat-value small">{score}</strong>
            </div>
            <button type="button" onClick={handleSubmit} disabled={submitting}>
              {submitting ? 'Salvando resultado...' : 'Salvar respostas'}
            </button>
          </div>

          {error ? <div className="alert error">{error}</div> : null}

          {result ? (
            <div className="alert success">
              <strong>Resultado salvo:</strong> {result.classificacao} com pontuacao {result.pontuacao}.
            </div>
          ) : null}
        </article>

        <article className="section-card">
          <div className="section-heading">
            <div>
              <h2>Ultimas aplicacoes</h2>
            </div>
          </div>

          {loadingHistory ? <div className="empty-state">Carregando historico...</div> : null}

          {!loadingHistory && history.length === 0 ? (
            <div className="empty-state">Nenhuma resposta salva ainda.</div>
          ) : null}

          <div className="stack-list">
            {history.map((item) => (
              <div key={item.id} className="result-card">
                <div className="recommendation-header">
                  <strong>{item.classificacao}</strong>
                  <span className="score-badge">{item.pontuacao}</span>
                </div>
                <small>{formatDate(item.criado_em)}</small>
              </div>
            ))}
          </div>
        </article>
      </section>
    </Layout>
  );
}
