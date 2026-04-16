import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import Layout from '../components/Layout';
import { appService } from '../services/app';
import type { EducationalContent } from '../types/app';

export default function Contents() {
  const [contents, setContents] = useState<EducationalContent[]>([]);
  const [category, setCategory] = useState('Todas');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let active = true;

    const loadContents = async () => {
      try {
        const response = await appService.listContents();
        if (active) {
          setContents(response);
        }
      } catch {
        if (active) {
          setError('Nao foi possivel carregar a biblioteca de conteudos.');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadContents();

    return () => {
      active = false;
    };
  }, []);

  const categories = useMemo(() => {
    return ['Todas', ...new Set(contents.map((item) => item.categoria))];
  }, [contents]);

  const filteredContents = useMemo(() => {
    const normalizedQuery = deferredQuery.trim().toLowerCase();
    return contents.filter((content) => {
      const matchesCategory = category === 'Todas' || content.categoria === category;
      const haystack = `${content.titulo} ${content.resumo} ${content.conteudo}`.toLowerCase();
      const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
      return matchesCategory && matchesQuery;
    });
  }, [category, contents, deferredQuery]);

  return (
    <Layout>
      <section className="section-card">
        <div className="section-heading">
          <div>
            <h2>Conteudos</h2>
          </div>
          <span className="pill">{filteredContents.length} itens exibidos</span>
        </div>

        <p>Materiais curtos para leitura tranquila.</p>

        <div className="toolbar">
          <label className="field compact-field">
            <span>Buscar</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ex.: sono, ansiedade, rotina" />
          </label>

          <label className="field compact-field">
            <span>Categoria</span>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>

        {loading ? <div className="empty-state">Carregando conteudos...</div> : null}
        {error ? <div className="alert error">{error}</div> : null}

        {!loading && !filteredContents.length ? (
          <div className="empty-state">Nenhum conteudo encontrado com os filtros atuais.</div>
        ) : null}

        <div className="content-grid">
          {filteredContents.map((content) => (
            <article key={content.slug} className="content-card large">
              <div className="recommendation-header">
                <span className="pill">{content.categoria}</span>
                <span className="pill subtle">{content.nivel.toUpperCase()}</span>
              </div>
              <h3>{content.titulo}</h3>
              <p>{content.resumo}</p>
              <details className="content-details">
                <summary>Ler mais</summary>
                <div className="divider" />
                <p>{content.conteudo}</p>
              </details>
            </article>
          ))}
        </div>
      </section>
    </Layout>
  );
}


