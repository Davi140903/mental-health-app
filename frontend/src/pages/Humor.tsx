import { useState } from 'react';
import Layout from '../components/Layout';
import { appService } from '../services/app';

const moodOptions = [
  { value: 1, label: 'Muito ruim' },
  { value: 2, label: 'Ruim' },
  { value: 3, label: 'Neutro' },
  { value: 4, label: 'Bom' },
  { value: 5, label: 'Muito bom' },
];

export default function Humor() {
  const [selectedValue, setSelectedValue] = useState<number | null>(null);
  const [nota, setNota] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

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
      await appService.createMood({
        valor: selectedValue,
        nota: nota || undefined,
      });
      setFeedback('Registro salvo com sucesso no backend.');
      setNota('');
    } catch {
      setError('N?o foi poss?vel salvar o humor.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout>
      <section className="single-panel-layout">
        <article className="section-card">
          <div className="section-heading">
            <div>
              <h2>Registrar humor</h2>
            </div>
          </div>
          <p>Escolha como você está se sentindo agora.</p>

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
      </section>
    </Layout>
  );
}
