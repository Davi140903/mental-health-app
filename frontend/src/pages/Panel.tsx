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

  return 'Mais favorável';
}

function normalizeTopicLabel(topic: string) {
  const normalized = topic.trim().toLowerCase();
  const topicMap: Record<string, string> = {
    ansiedade: 'cabeça acelerada',
    'pressao do dia a dia': 'dias mais pesados',
    'trabalho ou estudos': 'rotina e cobrancas',
    sono: 'sono',
    humor: 'como você tem se sentido',
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
          setError('Não foi possível carregar seu painel agora.');
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
          <div className="alert error">{error || 'Não foi possível montar o painel.'}</div>
        </section>
      </Layout>
    );
  }

  const lastMoodDate = data.ultimo_humor ? formatDate(data.ultimo_humor.criado_em) : 'Sem registro ainda';
  const lastConversation = data.memoria_lia.recent_conversations[0] ?? null;
  const periodSummary =
    data.memoria_lia.recent_summary ??
    data.memoria_lia.summary ??
    'A Lia ainda está juntando mais contexto para montar um retrato breve daqui.';
  const triageSummary = data.triagem_atual
    ? data.triagem_atual.status === 'scheduled'
      ? `Triagem marcada com ${data.triagem_atual.psychologist_name ?? 'psicólogo'} para ${formatDate(data.triagem_atual.scheduled_for ?? data.triagem_atual.requested_at)}.`
      : 'Você já tem um pedido de triagem em andamento e pode concluir o agendamento com um psicólogo.'
    : null;

  return (
    <Layout>
      <div className="dashboard-shell user-panel-shell">
        <section className="dashboard-intro panel-hero">
          <div>
            <span className="pill">Seu panorama</span>
          <h2>{data.usuario.nome}, aqui está um retrato breve do que vem aparecendo</h2>
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
            <span className="stat-label">Conversas com a Lia</span>
            <strong className="stat-value">{data.estatisticas.total_conversas_lia}</strong>
            <p>Histórico que ajuda a dar continuidade ao seu cuidado.</p>
          </article>
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Cuidados que podem fazer sentido agora</h3>
                <p className="section-copy">Sugestões simples com base no que já apareceu no seu acompanhamento.</p>
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

        {triageSummary ? (
          <section className="section-card">
            <div className="section-heading">
              <div>
                <h3>Triagem com psicólogo</h3>
                <p className="section-copy">Quando você encerra com a Lia e pede continuidade, o acompanhamento aparece aqui.</p>
              </div>
            </div>
            <div className="summary-block calm-card">
              <p>{triageSummary}</p>
            </div>
          </section>
        ) : null}

        <section className="panel-content-grid">
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Últimas conversas com a Lia</h3>
                <p className="section-copy">Trechos resumidos para você lembrar do que já foi dito por aqui, sem pesar demais.</p>
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
                <h3>Conteúdos para seguir por perto</h3>
                <p className="section-copy">Sugestões escolhidas a partir do que já apareceu na sua jornada.</p>
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

        <section className="panel-content-grid">
          <article className="section-card">
            <div className="section-heading">
              <div>
                <h3>Um resumo simples do que mais vem aparecendo no seu acompanhamento.</h3>
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
                  <strong>Última conversa guardada</strong>
                  <p>{lastConversation?.summary ?? 'Assim que você terminar mais conversas com a Lia, esse bloco fica mais rico.'}</p>
                </div>
              </div>
              <div className="list-row stretch">
                <div>
                  <strong>Registros no app</strong>
                  <p>
                    Você já deixou {data.estatisticas.total_registros_humor} registro{data.estatisticas.total_registros_humor === 1 ? '' : 's'} de humor e{' '}
                    {data.estatisticas.triagens_realizadas} triagem{data.estatisticas.triagens_realizadas === 1 ? '' : 'ens'} breve{data.estatisticas.triagens_realizadas === 1 ? '' : 's'}.
                  </p>
                </div>
              </div>
              <div className="list-row stretch">
                <div>
                  <strong>Ultimo registro de humor</strong>
                  <p>
                    {data.ultimo_humor
                      ? `Seu último apontamento ficou em ${formatMoodLabel(data.ultimo_humor.valor).toLowerCase()}, salvo em ${lastMoodDate}.`
                      : 'Seu último registro de humor vai aparecer aqui quando você salvar um apontamento.'}
                  </p>
                </div>
              </div>
              <div className="list-row stretch">
                <div>
                  <strong>Média recente de humor</strong>
                  <p>
                    {data.estatisticas.media_humor_7_dias !== null
                      ? `Nos últimos dias, sua média ficou em ${data.estatisticas.media_humor_7_dias.toFixed(1)} de 5.`
                      : 'Assim que você acumular mais registros, a média recente vai aparecer aqui.'}
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
              <span className="stat-label">Memória breve da Lia</span>
              <p>{periodSummary}</p>
            </div>
          </article>
        </section>
      </div>
    </Layout>
  );
}
