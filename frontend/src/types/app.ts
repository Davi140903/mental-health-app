import type { Usuario } from './auth';

export type QuestionnaireKind = 'phq9' | 'gad7';
export type LiaStage = 'opening' | 'support' | 'anxiety' | 'mood' | 'closing';
export type LiaTopicKey =
  | 'opening_state'
  | 'main_focus'
  | 'distress_nature'
  | 'distress_context'
  | 'functional_impact'
  | 'frequency_duration'
  | 'concrete_example'
  | 'user_summary'
  | 'closing';

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
  total_conversas_lia: number;
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
  memoria_lia: LiaMemorySnapshot;
  triagem_atual: TriageRequest | null;
}

export interface ExportData {
  usuario: Usuario;
  humores: MoodEntry[];
  questionarios: QuestionnaireResult[];
  lia_interacoes: LiaRecentInteraction[];
  exportado_em: string;
}

export interface LiaTranscriptMessage {
  role: 'assistant' | 'user';
  content: string;
}

export interface LiaRecentInteraction {
  id?: string | null;
  created_at: string;
  opening_label?: string | null;
  opening_value?: string | null;
  summary: string;
  report?: string | null;
  topics: string[];
  status?: string;
  finalized?: boolean;
}

export interface LiaTopicState {
  filled: boolean;
  confidence: number;
  value: string | null;
}

export interface LiaMemorySnapshot {
  summary: string | null;
  recent_summary: string | null;
  topics: string[];
  conversation_count: number;
  is_first_contact: boolean;
  light_prompt_label?: string | null;
  light_prompt_value?: string | null;
  recent_conversations: LiaRecentInteraction[];
  latest_report?: string | null;
}

export interface LiaSession {
  session_key?: string | null;
  active_interaction_id?: string | null;
  stage: LiaStage;
  current_topic: LiaTopicKey;
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
  followup_mode?: boolean;
  followup_turns_left?: number;
  followup_finished?: boolean;
  pause_offer_pending?: boolean;
  pause_used?: boolean;
  recent_question_intents?: string[];
  topic_states: Record<string, LiaTopicState>;
  memory: LiaMemorySnapshot;
}

export interface LiaTurnResponse {
  session: LiaSession;
  refresh_dashboard: boolean;
  using_ollama: boolean;
}

export interface TriageSlot {
  id: number;
  psychologist_name: string;
  starts_at: string;
  ends_at: string;
  available: boolean;
}

export interface TriageRequest {
  id: string;
  status: string;
  psychologist_name?: string | null;
  notes?: string | null;
  requested_at: string;
  scheduled_for?: string | null;
  slot_id?: number | null;
  lia_interaction_id?: string | null;
}
