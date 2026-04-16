import type { Usuario } from './auth';

export type QuestionnaireKind = 'phq9' | 'gad7';
export type LiaStage = 'opening' | 'support' | 'anxiety' | 'mood' | 'closing';

export interface MoodEntry {
  id: string;
  valor: number;
  nota: string | null;
  criado_em: string;
}

export interface MoodEntryCreate {
  valor: number;
  nota?: string;
}

export interface QuestionnaireResult {
  id: string;
  tipo: QuestionnaireKind;
  respostas: number[];
  pontuacao: number;
  classificacao: string;
  criado_em: string;
}

export interface QuestionnaireSubmission {
  respostas: number[];
}

export interface EducationalContent {
  id: number;
  slug: string;
  titulo: string;
  categoria: string;
  resumo: string;
  conteudo: string;
  nivel: string;
  questionario_tipo: QuestionnaireKind | null;
  criado_em: string;
}

export interface DashboardStats {
  total_registros_humor: number;
  media_humor_7_dias: number | null;
  triagens_realizadas: number;
  ultima_triagem_phq9: number | null;
  ultima_triagem_gad7: number | null;
}

export interface MoodHistoryPoint {
  data: string;
  valor: number;
}

export interface Recommendation {
  titulo: string;
  descricao: string;
  prioridade: 'baixa' | 'media' | 'alta';
}

export interface DashboardData {
  usuario: Usuario;
  estatisticas: DashboardStats;
  ultimo_humor: MoodEntry | null;
  ultimos_questionarios: QuestionnaireResult[];
  historico_humor: MoodHistoryPoint[];
  recomendacoes: Recommendation[];
  conteudos_em_destaque: EducationalContent[];
}

export interface ExportData {
  usuario: Usuario;
  humores: MoodEntry[];
  questionarios: QuestionnaireResult[];
  exportado_em: string;
}

export interface LiaTranscriptMessage {
  role: 'assistant' | 'user';
  content: string;
}

export interface LiaMemorySnapshot {
  summary: string | null;
  recent_summary: string | null;
  topics: string[];
  conversation_count: number;
  is_first_contact: boolean;
}

export interface LiaSession {
  stage: LiaStage;
  turn_count: number;
  clarification_streak?: number;
  transcript: LiaTranscriptMessage[];
  gad7_scores: Array<number | null>;
  phq9_scores: Array<number | null>;
  mood_value: number | null;
  focus_kind: QuestionnaireKind | null;
  completed: boolean;
  saved_questionnaires: QuestionnaireKind[];
  saved_mood: boolean;
  memory: LiaMemorySnapshot;
}

export interface LiaTurnResponse {
  session: LiaSession;
  refresh_dashboard: boolean;
  using_ollama: boolean;
}
