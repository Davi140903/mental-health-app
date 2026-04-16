import { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import { appService } from '../services/app';
import type { MoodEntry } from '../types/app';

const moodOptions = [
  { value: 1, label: 'Muito ruim' },
  { value: 2, label: 'Ruim' },
  { value: 3, label: 'Neutro' },
  { value: 4, label: 'Bom' },
  { value: 5, label: 'Muito bom' },
];

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

export default function Humor() {
  const [selectedValue, setSelectedValue] = useState<number | null>(null);
  const [nota, setNota] = useState('');
  const [entries, setEntries] = useState<MoodEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;

    const loadEntries = async () => {
      try {
        const response = await appService.listMoods();
        if (active) {
          setEntries(response);
        }
      } catch {
        if (active) {
          setError('Nao foi possivel carregar os registros de humor.');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadEntries();

    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFeedback('');
    setError('');

    if (!selectedValue) {
      setError('Selecione um nivel de humor para salvar o registro.');
      return;
    }

    setSubmitting(true);
    try {
      const createdEntry = await appService.createMood({
        valor: selectedValue,
        nota: nota || undefined,
      });
      setEntries((current) => [createdEntry, ...current]);
      setFeedback('Registro salvo com sucesso no backend.');
      setNota('');
    } catch {
      setError('Nao foi possivel salvar o humor.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout>
      <section className="split-layout">
        <article className="section-card">
          <div className="section-heading">
            <div>
              <h2>Registrar humor</h2>
            </div>
          </div>
          <p>Escolha como voce esta se sentindo agora.</p>

          {feedback ? <div className="alert success">{feedback}</div> : null}
          {error ? <div className="alert error">{error}</div> : null}

          <form className="form-grid" onSubmit={handleSubmit}>
            <div className="option-grid">
              {moodOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={selectedValue === option.value ? 'choice active' : 'choice'}
                  onClick={() => setSelectedValue(option.value)}
                >
                  <strong>{option.label}</strong>
                </button>
              ))}
            </div>

            <label className="field">
              <span>Observacao opcional</span>
              <textarea
                rows={5}
                value={nota}
                onChange={(event) => setNota(event.target.value)}
                placeholder="Ex.: prova, sono ruim, discussao, dia tranquilo, tempo de descanso..."
              />
            </label>

            <button type="submit" disabled={submitting}>
              {submitting ? 'Salvando...' : 'Salvar registro'}
            </button>
          </form>
        </article>

        <article className="section-card">
          <div className="section-heading">
            <div>
              <h2>Ultimos registros</h2>
            </div>
          </div>

          {loading ? <div className="empty-state">Carregando registros...</div> : null}

          {!loading && entries.length === 0 ? (
            <div className="empty-state">Nenhum registro salvo ainda.</div>
          ) : null}

          <div className="stack-list">
            {entries.map((entry) => {
              const currentMood = moodOptions.find((option) => option.value === entry.valor);
              return (
                <div key={entry.id} className="list-row stretch">
                  <div>
                    <strong>{currentMood?.label ?? `Nivel ${entry.valor}`}</strong>
                    <p>{formatDate(entry.criado_em)}</p>
                    <p>{entry.nota || 'Sem observacao adicional.'}</p>
                  </div>
                  <span className="score-badge">{entry.valor}</span>
                </div>
              );
            })}
          </div>
        </article>
      </section>
    </Layout>
  );
}


