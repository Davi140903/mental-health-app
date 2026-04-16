import api from './api';
import type {
  DashboardData,
  EducationalContent,
  LiaSession,
  LiaTurnResponse,
  MoodEntry,
  MoodEntryCreate,
  QuestionnaireKind,
  QuestionnaireResult,
  QuestionnaireSubmission,
} from '../types/app';

export const appService = {
  async getDashboard(): Promise<DashboardData> {
    const response = await api.get<DashboardData>('/dashboard');
    return response.data;
  },

  async listMoods(limit = 30): Promise<MoodEntry[]> {
    const response = await api.get<MoodEntry[]>('/moods', { params: { limit } });
    return response.data;
  },

  async createMood(data: MoodEntryCreate): Promise<MoodEntry> {
    const response = await api.post<MoodEntry>('/moods', data);
    return response.data;
  },

  async listQuestionnaireResults(kind?: QuestionnaireKind): Promise<QuestionnaireResult[]> {
    const response = await api.get<QuestionnaireResult[]>('/questionnaires', {
      params: kind ? { tipo: kind } : undefined,
    });
    return response.data;
  },

  async submitQuestionnaire(
    kind: QuestionnaireKind,
    data: QuestionnaireSubmission,
  ): Promise<QuestionnaireResult> {
    const response = await api.post<QuestionnaireResult>(`/questionnaires/${kind}`, data);
    return response.data;
  },

  async listContents(category?: string): Promise<EducationalContent[]> {
    const response = await api.get<EducationalContent[]>('/contents', {
      params: category ? { categoria: category } : undefined,
    });
    return response.data;
  },

  async startLiaConversation(): Promise<LiaTurnResponse> {
    const response = await api.post<LiaTurnResponse>('/lia/start');
    return response.data;
  },

  async sendLiaMessage(message: string, session: LiaSession): Promise<LiaTurnResponse> {
    const response = await api.post<LiaTurnResponse>('/lia/message', {
      message,
      session,
    });
    return response.data;
  },
};
