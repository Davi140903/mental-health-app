import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { appService } from '../services/app';
import type { DashboardData } from '../types/app';

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function formatMoodLabel(value: number | null) {
  if (value === null) {
    return 'Sem registro recente';
  }

  if (value <= 2) {
    return 'Em alerta';
  }

  if (value === 3) {
    return 'Estavel';
  }

  return 'Mais favoravel';
}

function normalizeTopicLabel(topic: string) {
  const normalized = topic.trim().toLowerCase();
  const topicMap: Record<string, string> = {
    ansiedade: 'cabeca acelerada',
    'pressao do dia a dia': 'dias mais pesados',
    'trabalho ou estudos': 'rotina e cobrancas',
    sono: 'sono',
    humor: 'como voce tem se sentido',
    energia: 'energia',
    relacionamentos: 'relacoes e convivio',
    'corpo em alerta': 'corpo em alerta',
  };

  return topicMap[normalized] ?? topic;
}

export default function Panel() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;

    const loadDashboard = async () => {
      try {
        const response = await appService.getDashboard();
        if (active) {
          setData(response);
        }
      } catch {
        if (active) {
          setError('Nao foi possivel carregar seu painel agora.');
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

  const conversationHighlights = useMemo(() => {
    if (!data) {
      return [];
    }

    return Array.from(
      new Set([
        ...data.memoria_lia.topics.map(normalizeTopicLabel),
        ...data.memoria_lia.recent_conversations.flatMap((conversation) => conversation.topics.map(normalizeTopicLabel)),
      ]),
    ).slice(0, 8);
  }, [data]);

  if (loading) {
    return (
      <Layout>
        <section className="section-card">
          <div className="empty-state">Carregando seu painel...</div>
        </section>
      </Layout>
    );
  }

  if (error || !data) {
    return (
      <Layout>
        <section className="section-card">
          <div className="alert error">{error || 'Nao foi possivel montar o painel.'}</div>
        </section>
      </Layout>
    );
  }

  const lastMoodDate = data.ultimo_humor ? formatDate(data.ultimo_humor.criado_em) : 'Sem registro ainda';
  const lastConversation = data.memoria_lia.recent_conversations[0] ?? null;
  const periodSummary =
    data.memoria_lia.recent_summary ??
    data.memoria_lia.summary ??
    'A Lia ainda esta juntando mais contexto para montar um retrato breve daqui.';

  return (
    <Layout>
      <div className="dashboard-shell user-panel-shell">
        <section className="dashboard-intro panel-hero">
          <div>
            <span className="pill">Seu panorama</span>
            <h2>{data.usuario.nome}, aqui esta um retrato breve do que vem aparecendo</h2>
            <p>
              A ideia deste painel e te mostrar o que a Lia vem guardando com cuidado, como seu humor tem aparecido e
              o que pode te ajudar a se perceber melhor ao longo do tempo.
            </p>
          </div>

          <div className="hero-actions">
            <Link to="/lia" className="link-button">
              Voltar para a Lia
            </Link>
            <Link to="/humor" className="ghost-link-button">
              Registrar humor
            </Link>
          </div>
        </section>

        <section className="dashboard-metrics-grid">
          <article className="section-card panel-stat-card">
            <span className="stat-label">Humor mais recente</span>
            <strong className="stat-value">{formatMoodLabel(data.ultimo_humor?.valor ?? null)}</strong>
            <p>{lastMoodDate}</p>
          </article>

          <article className="section-card panel-stat-card">
            <span className="stat-label">Media de humor em 7 dias</span>
            <strong className="stat-value">
              {data.estatisticas.media_humor_7_dias !== null ? data.estatisticas.media_humor_7_dias.toFixed(1) : '--'}
            </strong>
            <p>Com base nos ultimos registros salvos no app.</p>
          </article>

          <article className="section-card panel-stat-card">
            <span className="stat-label">Conversas com a Lia</span>
            <strong className="stat-value">{data.estatisticas.total_conversas_lia}</strong>
            <p>Historico que ajuda a dar continuidade ao seu cuidado.</p>
          </article>

          <article className="section-card panel-stat-card">
            <span className="stat-label">Triagens recentes</span>
            <strong className="stat-value">{data.estatisticas.triagens_realizadas}</strong>
            <p>Registros breves que ajudam a acompanhar como voce vem passando pelos dias.</p>
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Como esse periodo aparece no seu historico</h3>
                <p className="section-copy">Um resumo simples do que mais vem aparecendo no seu acompanhamento.</p>
              </div>
            </div>

            <div className="summary-block calm-card panel-story-block">
              <span className="stat-label">Leitura breve</span>
              <p>{periodSummary}</p>
            </div>

            <div className="divider" />

            <div className="stack-list">
              <div className="list-row stretch">
                <div>
                  <strong>Ultima conversa guardada</strong>
                  <p>{lastConversation?.summary ?? 'Assim que voce terminar mais conversas com a Lia, esse bloco fica mais rico.'}</p>
                </div>
              </div>
              <div className="list-row stretch">
                <div>
                  <strong>Registros no app</strong>
                  <p>
                    Voce ja deixou {data.estatisticas.total_registros_humor} registro{data.estatisticas.total_registros_humor === 1 ? '' : 's'} de humor e{' '}
                    {data.estatisticas.triagens_realizadas} triagem{data.estatisticas.triagens_realizadas === 1 ? '' : 'ens'} breve{data.estatisticas.triagens_realizadas === 1 ? '' : 's'}.
                  </p>
                </div>
              </div>
              <div className="list-row stretch">
                <div>
                  <strong>Ultimo registro de humor</strong>
                  <p>
                    {data.ultimo_humor
                      ? `Seu ultimo apontamento ficou em ${data.ultimo_humor.valor} de 5, salvo em ${lastMoodDate}.`
                      : 'Seu ultimo registro de humor vai aparecer aqui quando voce salvar um apontamento.'}
                  </p>
                </div>
              </div>
            </div>
          </article>

          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Temas que voltam com mais frequencia</h3>
                <p className="section-copy">Esses pontos ajudam a Lia a retomar a conversa com contexto.</p>
              </div>
            </div>

            {conversationHighlights.length ? (
              <div className="lia-topic-list" aria-label="Temas mais recorrentes nas conversas">
                {conversationHighlights.map((topic) => (
                  <span key={topic} className="pill subtle">
                    {topic}
                  </span>
                ))}
              </div>
            ) : (
              <div className="empty-state">Seus temas recorrentes vao aparecer aqui conforme a Lia aprender mais sobre seu contexto.</div>
            )}

            <div className="divider" />

            <div className="summary-block calm-card">
              <span className="stat-label">Memoria breve da Lia</span>
              <p>{periodSummary}</p>
            </div>
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Historico de humor</h3>
                <p className="section-copy">Uma leitura visual simples para acompanhar seus registros mais recentes.</p>
              </div>
            </div>

            {data.historico_humor.length ? (
              <div className="chart-bars compact-chart">
                {data.historico_humor.map((point) => (
                  <div key={`${point.data}-${point.valor}`} className="chart-bar-item">
                    <div className="chart-bar-track">
                      <div
                        className="chart-bar-fill"
                        style={{ height: `${Math.max(18, (point.valor / 5) * 100)}%` }}
                        title={`${point.data}: ${point.valor}`}
                      />
                    </div>
                    <strong>{point.valor}</strong>
                    <span className="stat-label">{point.data}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">Seus registros de humor vao aparecer aqui conforme voce salvar novos apontamentos.</div>
            )}
          </article>

          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Cuidados que podem fazer sentido agora</h3>
                <p className="section-copy">Sugestoes simples com base no que ja apareceu no seu acompanhamento.</p>
              </div>
            </div>

            <div className="stack-list">
              {data.recomendacoes.map((item) => (
                <div key={`${item.titulo}-${item.prioridade}`} className="recommendation-card">
                  <div className="recommendation-header">
                    <strong>{item.titulo}</strong>
                    <span className={`priority-tag ${item.prioridade}`}>{item.prioridade}</span>
                  </div>
                  <p>{item.descricao}</p>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Ultimas conversas com a Lia</h3>
                <p className="section-copy">Trechos resumidos para voce lembrar do que ja foi dito por aqui, sem pesar demais.</p>
              </div>
            </div>

            {data.memoria_lia.recent_conversations.length ? (
              <div className="stack-list">
                {data.memoria_lia.recent_conversations.map((item) => (
                  <div key={`${item.created_at}-${item.summary}`} className="compact-card">
                    <div className="recommendation-header">
                      <strong>{formatDate(item.created_at)}</strong>
                      {item.opening_value ? <span className="pill subtle">{item.opening_value}</span> : null}
                    </div>
                    <p>{item.summary}</p>
                    {item.report ? <p className="panel-secondary-copy">{item.report}</p> : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">Depois das suas conversas com a Lia, os resumos mais importantes vao aparecer aqui.</div>
            )}
          </article>

          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Conteudos para seguir por perto</h3>
                <p className="section-copy">Sugestoes escolhidas a partir do que ja apareceu na sua jornada.</p>
              </div>
            </div>

            <div className="stack-list">
              {data.conteudos_em_destaque.map((content) => (
                <div key={content.slug} className="compact-card">
                  <div className="recommendation-header">
                    <strong>{content.titulo}</strong>
                    <span className="pill">{content.categoria}</span>
                  </div>
                  <p>{content.resumo}</p>
                </div>
              ))}
            </div>
          </article>
        </section>
      </div>
    </Layout>
  );
}
