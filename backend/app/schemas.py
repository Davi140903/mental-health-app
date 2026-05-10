from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UsuarioCreate(BaseModel):
    email: EmailStr
    nome: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=100)
    consentimento_lgpd: bool
    codigo: str = Field(min_length=6, max_length=6)


class LoginData(BaseModel):
    email: EmailStr
    password: str
    codigo: str = Field(min_length=6, max_length=6)


class EmailCodeRequest(BaseModel):
    email: EmailStr


class LoginCodeRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)


class PasswordResetCodeRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    codigo: str = Field(min_length=6, max_length=6)
    nova_senha: str = Field(min_length=6, max_length=100)


class CodeRequestOut(BaseModel):
    detail: str
    expires_in_minutes: int
    debug_code: str | None = None


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    nome: str
    role: Literal["user", "psychologist", "admin"] = "user"
    consentimento_lgpd: bool
    criado_em: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileUpdate(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    consentimento_lgpd: bool


class AdminPsychologistCreate(BaseModel):
    email: EmailStr
    nome: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=100)
    consentimento_lgpd: bool = True


class AdminPsychologistUpdate(BaseModel):
    email: EmailStr
    nome: str = Field(min_length=2, max_length=120)
    password: str | None = Field(default=None, min_length=6, max_length=100)
    consentimento_lgpd: bool = True


class MoodEntryCreate(BaseModel):
    valor: int = Field(ge=1, le=5)
    nota: str | None = Field(default=None, max_length=500)


class MoodEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    valor: int
    nota: str | None
    criado_em: datetime


class QuestionnaireSubmission(BaseModel):
    respostas: list[int]


class QuestionnaireResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo: str
    respostas: list[int]
    pontuacao: int
    classificacao: str
    criado_em: datetime


class EducationalContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    titulo: str
    categoria: str
    resumo: str
    conteudo: str
    nivel: str
    questionario_tipo: str | None
    criado_em: datetime


class DashboardStatOut(BaseModel):
    total_registros_humor: int
    media_humor_7_dias: float | None
    triagens_realizadas: int
    ultima_triagem_phq9: int | None
    ultima_triagem_gad7: int | None
    total_conversas_lia: int


class MoodHistoryPoint(BaseModel):
    data: str
    valor: int


class RecommendationOut(BaseModel):
    titulo: str
    descricao: str
    prioridade: Literal["baixa", "media", "alta"]


class DashboardOut(BaseModel):
    usuario: UsuarioOut
    estatisticas: DashboardStatOut
    ultimo_humor: MoodEntryOut | None
    ultimos_questionarios: list[QuestionnaireResultOut]
    historico_humor: list[MoodHistoryPoint]
    recomendacoes: list[RecommendationOut]
    conteudos_em_destaque: list[EducationalContentOut]
    memoria_lia: LiaMemorySnapshot
    triagem_atual: TriageRequestOut | None = None


class ExportDataOut(BaseModel):
    usuario: UsuarioOut
    humores: list[MoodEntryOut]
    questionarios: list[QuestionnaireResultOut]
    lia_interacoes: list[LiaRecentInteraction] = Field(default_factory=list)
    exportado_em: datetime


class LiaTranscriptMessage(BaseModel):
    role: Literal["assistant", "user"]
    content: str = Field(min_length=1, max_length=2000)


class LiaRecentInteraction(BaseModel):
    id: str | None = None
    created_at: datetime
    opening_label: str | None = None
    opening_value: str | None = None
    summary: str
    report: str | None = None
    topics: list[str] = Field(default_factory=list)
    status: str = "final"
    finalized: bool = True


class LiaTopicState(BaseModel):
    filled: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    value: str | None = None


class LiaMemorySnapshot(BaseModel):
    summary: str | None = None
    recent_summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    conversation_count: int = 0
    is_first_contact: bool = True
    light_prompt_label: str | None = None
    light_prompt_value: str | None = None
    recent_conversations: list[LiaRecentInteraction] = Field(default_factory=list)
    latest_report: str | None = None


class LiaSessionState(BaseModel):
    session_key: str | None = None
    active_interaction_id: str | None = None
    stage: Literal["opening", "support", "anxiety", "mood", "closing"] = "opening"
    current_topic: Literal[
        "opening_state",
        "main_focus",
        "distress_nature",
        "distress_context",
        "functional_impact",
        "frequency_duration",
        "concrete_example",
        "user_summary",
        "closing",
    ] = "opening_state"
    turn_count: int = Field(default=0, ge=0, le=12)
    clarification_streak: int = Field(default=0, ge=0, le=6)
    transcript: list[LiaTranscriptMessage] = Field(default_factory=list)
    gad7_scores: list[int | None] = Field(default_factory=lambda: [None] * 7)
    phq9_scores: list[int | None] = Field(default_factory=lambda: [None] * 9)
    mood_value: int | None = Field(default=None, ge=1, le=5)
    focus_kind: Literal["gad7", "phq9"] | None = None
    completed: bool = False
    saved_questionnaires: list[Literal["gad7", "phq9"]] = Field(default_factory=list)
    saved_mood: bool = False
    followup_mode: bool = False
    followup_turns_left: int = Field(default=0, ge=0, le=3)
    followup_finished: bool = False
    pause_offer_pending: bool = False
    pause_used: bool = False
    recent_question_intents: list[str] = Field(default_factory=list)
    topic_states: dict[str, LiaTopicState] = Field(
        default_factory=lambda: {
            "opening_state": LiaTopicState(),
            "main_focus": LiaTopicState(),
            "distress_nature": LiaTopicState(),
            "distress_context": LiaTopicState(),
            "functional_impact": LiaTopicState(),
            "frequency_duration": LiaTopicState(),
            "concrete_example": LiaTopicState(),
            "user_summary": LiaTopicState(),
        }
    )
    memory: LiaMemorySnapshot = Field(default_factory=LiaMemorySnapshot)


class LiaTurnInput(BaseModel):
    session: LiaSessionState
    message: str = Field(min_length=1, max_length=2000)


class LiaTurnOut(BaseModel):
    session: LiaSessionState
    refresh_dashboard: bool = False
    using_ollama: bool = False


class TriageSlotOut(BaseModel):
    id: int
    psychologist_name: str
    starts_at: datetime
    ends_at: datetime
    available: bool


class TriageRequestCreate(BaseModel):
    interaction_id: str | None = None


class TriageScheduleInput(BaseModel):
    request_id: str
    slot_id: int


class TriageRequestOut(BaseModel):
    id: str
    status: str
    psychologist_name: str | None = None
    notes: str | None = None
    requested_at: datetime
    scheduled_for: datetime | None = None
    slot_id: int | None = None
    lia_interaction_id: str | None = None


class PsychologistTriageRequestOut(BaseModel):
    id: str
    status: str
    requested_at: datetime
    scheduled_for: datetime | None = None
    psychologist_name: str | None = None
    notes: str | None = None
    user: UsuarioOut
    interaction: LiaRecentInteraction | None = None


class LiaAnalysis(BaseModel):
    assistant_reply: str | None = Field(default=None, max_length=600)
    reflection: str = Field(min_length=1, max_length=400)
    next_question: str | None = Field(default=None, max_length=300)
    risk_level: Literal["none", "attention", "urgent"] = "none"
    mood_value: int | None = Field(default=None, ge=1, le=5)
    gad7_scores: list[int | None] = Field(default_factory=lambda: [None] * 7)
    phq9_scores: list[int | None] = Field(default_factory=lambda: [None] * 9)
    ready_to_close: bool = False
    recommended_stage: Literal["support", "anxiety", "mood", "closing"] = "support"
