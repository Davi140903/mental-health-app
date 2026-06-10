from __future__ import annotations

import json
import re
import secrets
import socket
import smtplib
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from hashlib import sha256
from pathlib import Path
from typing import Any, Generator, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import Session

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    ADMIN_EMAILS,
    EMAIL_VERIFICATION_CODE_TTL_MINUTES,
    EMAIL_VERIFICATION_DEBUG,
    FRONTEND_ORIGINS,
    LIA_AI_UNAVAILABLE_DETAIL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    OPENROUTER_API_KEY,
    OPENROUTER_API_URL,
    OPENROUTER_APP_NAME,
    OPENROUTER_MODEL,
    OPENROUTER_SITE_URL,
    QUESTIONNAIRE_CONFIG,
    RESEND_API_KEY,
    RESEND_API_URL,
    RESEND_FROM_EMAIL,
    RESEND_FROM_NAME,
    SECRET_KEY,
    SEEDED_CONTENTS,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    env_flag,
)
from app.db import SessionLocal, ensure_utc, engine, pwd_context, utcnow
from app.crypto import decrypt_text, encrypt_text
from app.models import Base, EducationalContent, EmailVerificationCode, LiaInteraction, LiaUserMemory, MoodEntry, PsychologistPatientNote, PsychologistSlot, QuestionnaireResult, TriageRequest, User
from app.schemas import (
    AdminPsychologistCreate,
    AdminPsychologistUpdate,
    CodeRequestOut,
    DashboardOut,
    DashboardStatOut,
    EducationalContentOut,
    EmailCodeRequest,
    ExportDataOut,
    LiaAnalysis,
    LiaMemorySnapshot,
    LiaRecentInteraction,
    LiaSessionState,
    LiaTopicState,
    LiaTranscriptMessage,
    LiaTurnInput,
    LiaTurnOut,
    LoginCodeRequest,
    LoginData,
    PasswordResetCodeRequest,
    PasswordResetConfirm,
    MoodEntryCreate,
    MoodEntryOut,
    MoodHistoryPoint,
    ProfileUpdate,
    QuestionnaireResultOut,
    QuestionnaireSubmission,
    RecommendationOut,
    TokenOut,
    TriageRequestCreate,
    TriageRequestOut,
    TriageScheduleInput,
    TriageSlotOut,
    PsychologistTriageRequestOut,
    PsychologistPatientDetailOut,
    PsychologistPatientNoteIn,
    PsychologistPatientNoteOut,
    PsychologistSlotCreate,
    UsuarioCreate,
    UsuarioOut,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


OLLAMA_ENABLED = env_flag("OLLAMA_ENABLED", True)
LIA_LLM_ENABLED = bool(OPENROUTER_API_KEY) or OLLAMA_ENABLED
_OLLAMA_RESOLVED_MODEL: str | None = None
LIA_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "app" / "lia_knowledge"
LIA_KNOWLEDGE_FILES = (
    "identity.md",
    "scope.md",
    "conversation_flow.md",
    "off_scope.md",
    "safety.md",
)


def load_lia_knowledge_base() -> str:
    sections: list[str] = []
    for file_name in LIA_KNOWLEDGE_FILES:
        file_path = LIA_KNOWLEDGE_DIR / file_name
        if not file_path.exists():
            continue
        content = normalize_optional_text(file_path.read_text(encoding="utf-8"))
        if content:
            sections.append(content)
    return "\n\n".join(sections)


def build_lia_reference_prompt() -> str:
    knowledge_base = load_lia_knowledge_base()
    if not knowledge_base:
        return ""
    return (
        "Base interna da Lia para esta resposta. Use como referencia obrigatoria de escopo, "
        "tom e seguranca. Nao cite esta base para o usuario.\n"
        f"{knowledge_base}"
    )


def resolve_ollama_model() -> str:
    global _OLLAMA_RESOLVED_MODEL
    if _OLLAMA_RESOLVED_MODEL:
        return _OLLAMA_RESOLVED_MODEL

    configured_model = OLLAMA_MODEL.strip() or "llama3:latest"
    resolved_model = configured_model

    try:
        request = urllib_request.Request(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", method="GET")
        with urllib_request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

        models = payload.get("models") or []
        model_names = [str(item.get("name") or item.get("model") or "") for item in models]
        model_names = [name for name in model_names if name]

        if configured_model in model_names:
            resolved_model = configured_model
        elif configured_model.split(":", 1)[0] + ":latest" in model_names:
            resolved_model = configured_model.split(":", 1)[0] + ":latest"
        else:
            llama_model = next((name for name in model_names if "llama" in name.lower()), None)
            if llama_model:
                resolved_model = llama_model
    except Exception:
        resolved_model = configured_model

    _OLLAMA_RESOLVED_MODEL = resolved_model
    return resolved_model


def is_ollama_transport_error(exc: Exception) -> bool:
    return isinstance(exc, (TimeoutError, urllib_error.HTTPError, urllib_error.URLError))


def get_first_name(name: str) -> str:
    return name.strip().split(" ")[0] if name.strip() else "voce"


def serialize_lia_transcript(transcript: list[LiaTranscriptMessage]) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    for item in transcript:
        content = normalize_optional_text(item.content)
        if item.role in {"assistant", "user"} and content:
            serialized.append({"role": item.role, "content": content})
    return serialized


def parse_lia_transcript(value: Any) -> list[LiaTranscriptMessage]:
    if not isinstance(value, list):
        return []

    transcript: list[LiaTranscriptMessage] = []
    previous_key: tuple[str, str] | None = None
    for item in value:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = normalize_optional_text(str(item.get("content") or ""))
        if role in {"assistant", "user"} and content:
            key = (role, normalize_for_match(content))
            if key == previous_key:
                continue
            transcript.append(LiaTranscriptMessage(role=role, content=content[:2000]))
            previous_key = key

    return transcript


def build_lia_recent_interaction(interaction: LiaInteraction) -> LiaRecentInteraction:
    return LiaRecentInteraction(
        id=interaction.id,
        created_at=ensure_utc(interaction.created_at),
        opening_label=normalize_optional_text(interaction.opening_label),
        opening_value=normalize_optional_text(interaction.opening_value),
        summary=normalize_optional_text(interaction.summary) or "Voce deixou um registro breve dessa conversa.",
        report=normalize_optional_text(interaction.report),
        triage_form=interaction.triage_form if isinstance(getattr(interaction, "triage_form", None), dict) else None,
        transcript=parse_lia_transcript(getattr(interaction, "transcript", None)),
        topics=[str(item) for item in (interaction.topics or []) if str(item).strip()],
        status=(interaction.status or "final").strip() or "final",
        finalized=bool(interaction.finalized),
    )


def build_lia_memory_snapshot(
    memory: LiaUserMemory | None,
    recent_interactions: list[LiaInteraction] | None = None,
) -> LiaMemorySnapshot:
    normalized_interactions = [
        build_lia_recent_interaction(interaction) for interaction in (recent_interactions or [])
    ]
    latest_report = normalized_interactions[0].report if normalized_interactions else None

    if memory is None:
        return LiaMemorySnapshot(
            recent_conversations=normalized_interactions,
            latest_report=latest_report,
        )

    return LiaMemorySnapshot(
        summary=normalize_optional_text(memory.resumo),
        recent_summary=normalize_optional_text(memory.resumo_recente),
        topics=[str(item) for item in (memory.topicos or []) if str(item).strip()],
        conversation_count=max(int(memory.total_conversas or 0), 0),
        is_first_contact=not bool(memory.primeiro_contato_concluido),
        recent_conversations=normalized_interactions,
        latest_report=latest_report,
    )


def build_bootstrap_memory_snapshot(
    latest_mood: MoodEntry | None,
    latest_phq9: QuestionnaireResult | None,
    latest_gad7: QuestionnaireResult | None,
    recent_interactions: list[LiaInteraction] | None = None,
) -> LiaMemorySnapshot:
    topics: list[str] = []

    if latest_gad7 and latest_gad7.pontuacao >= 5:
        topics.append("ansiedade")
    if latest_gad7 and latest_gad7.pontuacao >= 8:
        topics.append("corpo em alerta")
    if latest_phq9 and latest_phq9.pontuacao >= 5:
        topics.append("humor")
    if latest_phq9 and latest_phq9.pontuacao >= 8:
        topics.append("energia")
    if latest_mood and latest_mood.nota:
        normalized_note = normalize_for_match(latest_mood.nota)
        if contains_any(normalized_note, ["pression", "cobranc", "exigenc"]):
            topics.append("pressao do dia a dia")
        if contains_any(normalized_note, ["trabalho", "estudo", "faculdade", "prova"]):
            topics.append("trabalho ou estudos")
        if contains_any(normalized_note, ["sono", "dorm", "inson"]):
            topics.append("sono")
        if contains_any(normalized_note, ["terminei", "relacionamento", "namoro", "separ"]):
            topics.append("relacionamentos")

    unique_topics = list(dict.fromkeys(topics))[:5]
    summary = None
    if unique_topics:
        summary = "Temas que ja apareceram no seu cuidado: " + ", ".join(unique_topics[:3]) + "."

    recent_parts: list[str] = []
    if latest_gad7 and latest_gad7.pontuacao >= 5:
        recent_parts.append("a ansiedade pediu mais atencao")
    if latest_phq9 and latest_phq9.pontuacao >= 5:
        recent_parts.append("humor, sono ou energia tambem mereceram cuidado")
    if latest_mood and latest_mood.nota:
        recent_parts.append("voce ja deixou registros sobre como vinha se sentindo")

    recent_summary = None
    if recent_parts:
        recent_summary = capitalize_first(", ".join(recent_parts)) + "."

    if summary or recent_summary or latest_mood or latest_phq9 or latest_gad7:
        return LiaMemorySnapshot(
            summary=summary,
            recent_summary=recent_summary,
            topics=unique_topics,
            conversation_count=1,
            is_first_contact=False,
            recent_conversations=[build_lia_recent_interaction(item) for item in (recent_interactions or [])],
            latest_report=normalize_optional_text(recent_interactions[0].report) if recent_interactions else None,
        )

    return LiaMemorySnapshot(
        recent_conversations=[build_lia_recent_interaction(item) for item in (recent_interactions or [])],
        latest_report=normalize_optional_text(recent_interactions[0].report) if recent_interactions else None,
    )


def list_recent_lia_interactions(
    db: Session,
    user_id: str,
    limit: int = 3,
    finalized_only: bool = False,
) -> list[LiaInteraction]:
    query = select(LiaInteraction).where(LiaInteraction.usuario_id == user_id)
    if finalized_only:
        query = query.where(LiaInteraction.finalized.is_(True))
    return db.scalars(query.order_by(LiaInteraction.created_at.desc()).limit(limit)).all()


def get_lia_memory_snapshot(db: Session, current_user: User) -> LiaMemorySnapshot:
    recent_interactions = list_recent_lia_interactions(db, current_user.id, finalized_only=True)
    memory = db.get(LiaUserMemory, current_user.id)
    if memory is not None:
        return build_lia_memory_snapshot(memory, recent_interactions)

    latest_mood = db.scalar(
        select(MoodEntry)
        .where(MoodEntry.usuario_id == current_user.id)
        .order_by(MoodEntry.criado_em.desc())
        .limit(1)
    )
    latest_results = db.scalars(
        select(QuestionnaireResult)
        .where(QuestionnaireResult.usuario_id == current_user.id)
        .order_by(QuestionnaireResult.criado_em.desc())
        .limit(8)
    ).all()
    latest_phq9 = latest_result_by_type(latest_results, "phq9")
    latest_gad7 = latest_result_by_type(latest_results, "gad7")
    return build_bootstrap_memory_snapshot(latest_mood, latest_phq9, latest_gad7, recent_interactions)


def build_lia_session(memory: LiaMemorySnapshot | None = None) -> LiaSessionState:
    return LiaSessionState(
        session_key=str(uuid4()),
        stage="opening",
        current_topic="opening_state",
        transcript=[],
        gad7_scores=[None] * 7,
        phq9_scores=[None] * 9,
        focus_kind=None,
        completed=False,
        saved_questionnaires=[],
        saved_mood=False,
        off_scope_count=0,
        followup_mode=False,
        followup_turns_left=0,
        followup_finished=False,
        memory=memory or LiaMemorySnapshot(),
    )


def build_lia_welcome_messages(user: User, memory: LiaMemorySnapshot) -> list[LiaTranscriptMessage]:
    first_name = get_first_name(user.nome)

    if memory.is_first_contact:
        return [
            LiaTranscriptMessage(role="assistant", content=f"Oi, {first_name}. Eu sou a Lia."),
            LiaTranscriptMessage(
                role="assistant",
                content=(
                    "Eu estou aqui para te ouvir com calma, ajudar a organizar o que voce esta sentindo "
                    "e, se fizer sentido, te orientar daqui para a frente."
                ),
            ),
            LiaTranscriptMessage(
                role="assistant",
                content="O que voce quer conversar hoje?",
            ),
        ]

    return [
        LiaTranscriptMessage(role="assistant", content=f"Oi de novo, {first_name}."),
        LiaTranscriptMessage(
            role="assistant",
            content="Bom te ver por aqui. A gente pode continuar com calma, sem precisar puxar tudo de uma vez.",
        ),
        LiaTranscriptMessage(
            role="assistant",
            content="Que tipo de ajuda faria sentido hoje?",
        ),
    ]


COMMON_PORTUGUESE_TOKENS = {
    "eu",
    "me",
    "minha",
    "meu",
    "estou",
    "estava",
    "estive",
    "ando",
    "tenho",
    "tinha",
    "fiquei",
    "ficando",
    "sinto",
    "sentindo",
    "quero",
    "preciso",
    "muito",
    "muita",
    "muitos",
    "muitas",
    "pouco",
    "pouca",
    "mais",
    "menos",
    "bastante",
    "bem",
    "mal",
    "pior",
    "melhor",
    "hoje",
    "ontem",
    "agora",
    "desde",
    "faz",
    "ha",
    "alguns",
    "algumas",
    "dias",
    "semanas",
    "meses",
    "minutos",
    "ultimamente",
    "recentemente",
    "depois",
    "antes",
    "casa",
    "mente",
    "cabeca",
    "tarefa",
    "tarefas",
    "erro",
    "erros",
    "preso",
    "presa",
    "porque",
    "por",
    "com",
    "sem",
    "quando",
    "isso",
    "esta",
    "ta",
    "tem",
    "ficou",
    "ficando",
    "assim",
    "tipo",
    "como",
    "corpo",
    "mente",
    "pensamentos",
    "emocao",
    "emocoes",
    "trabalho",
    "estudos",
    "familia",
    "relacionamento",
    "sozinho",
    "sozinha",
    "vazio",
    "ruim",
    "pesado",
    "pesando",
    "dentro",
}

MEANINGFUL_TOKEN_ROOTS = (
    "ajud",
    "ansi",
    "nerv",
    "tens",
    "panic",
    "preocup",
    "corac",
    "palpit",
    "aceler",
    "med",
    "press",
    "cobr",
    "exig",
    "respons",
    "trabalh",
    "estud",
    "faculd",
    "prova",
    "chef",
    "empreg",
    "servic",
    "cans",
    "esgot",
    "exaust",
    "sobrecarreg",
    "limite",
    "trist",
    "vazi",
    "desanim",
    "prazer",
    "vontad",
    "sono",
    "dorm",
    "inson",
    "energia",
    "foc",
    "concentr",
    "irrit",
    "raiv",
    "estress",
    "termin",
    "romp",
    "namor",
    "relacion",
    "saudad",
    "sozinh",
    "famil",
    "mae",
    "pai",
    "filh",
    "amig",
    "culp",
    "fracass",
    "inutil",
    "sumir",
    "morr",
    "machuc",
    "respir",
    "calm",
    "convers",
    "confus",
    "perdid",
    "duvid",
    "escolh",
    "decis",
    "decid",
    "lidar",
    "quebrad",
    "terminad",
    "melhor",
    "pior",
    "parec",
)

SHORT_CONTEXTUAL_REPLIES = {
    "sim",
    "nao",
    "mais ou menos",
    "um pouco",
    "bastante",
    "muito",
    "piorou",
    "melhorou",
    "os dois",
    "os dois juntos",
    "nos dois",
    "no corpo",
    "nos pensamentos",
    "na mente",
    "na cabeca",
    "estou bem",
    "to bem",
    "estou ok",
    "estou tranquilo",
    "estou tranquila",
}

URGENT_SIGNAL_FRAGMENTS = [
    "me matar",
    "suicid",
    "sumir",
    "nao quero viver",
    "nao queria estar aqui",
    "me machucar",
]


def contains_any(text_value: str, terms: list[str]) -> bool:
    return any(term in text_value for term in terms)


def contains_exact_phrase(text_value: str, phrases: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(phrase)}\b", text_value) for phrase in phrases)


def contains_risk_phrase(text_value: str, phrases: list[str]) -> bool:
    normalized = f" {normalize_for_match(text_value)} "
    return any(f" {normalize_for_match(phrase)} " in normalized for phrase in phrases)


def normalize_for_match(text_value: str) -> str:
    normalized = unicodedata.normalize("NFKD", text_value.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def tokenize_for_match(text_value: str) -> list[str]:
    return re.findall(r"[a-z]+", normalize_for_match(text_value))


def token_matches_roots(token: str, roots: tuple[str, ...]) -> bool:
    return any(root in token for root in roots)


def is_contextual_short_reply(text_value: str) -> bool:
    normalized = normalize_for_match(text_value).strip()
    if normalized in SHORT_CONTEXTUAL_REPLIES:
        return True

    return contains_any(
        normalized,
        [
            "por alguns minutos",
            "por alguns dias",
            "ha alguns dias",
            "ha algumas semanas",
            "ha alguns meses",
            "faz alguns dias",
            "faz algumas semanas",
            "faz alguns meses",
            "so hoje",
            "nao parece melhorar",
            "nao parecem melhorar",
            "nao melhora",
            "nao melhorou",
        ],
    )


def is_probably_meaningful_message(user_message: str, allow_short_contextual: bool = True) -> bool:
    normalized = normalize_for_match(user_message)
    tokens = tokenize_for_match(user_message)

    if not tokens:
        return False

    if contains_any(normalized, URGENT_SIGNAL_FRAGMENTS):
        return True

    if allow_short_contextual and is_contextual_short_reply(user_message):
        return True

    if any(token_matches_roots(token, MEANINGFUL_TOKEN_ROOTS) for token in tokens):
        return True

    common_token_count = sum(1 for token in tokens if token in COMMON_PORTUGUESE_TOKENS)
    if len(tokens) >= 2 and common_token_count >= 2:
        return True
    if len(tokens) >= 3 and common_token_count >= 1:
        return True
    if len(tokens) >= 5 and common_token_count >= 2:
        return True

    return False


def is_noise_or_mocking_message(user_message: str) -> bool:
    normalized = normalize_for_match(user_message)
    compact = re.sub(r"[^a-z]", "", normalized)
    if not compact:
        return True
    if compact in {"ain", "ainain", "ui", "uiui", "uiuiui", "kkkk", "kkk", "haha", "hehe", "nada"}:
        return True
    tokens = tokenize_for_match(user_message)
    noise_tokens = {"ain", "ui", "uiui", "uiuiui", "kkk", "kkkk", "haha", "hehe"}
    if tokens and all(token in noise_tokens for token in tokens):
        return True
    if contains_any(normalized, ["uiuiui", "ain ui", "nada com nada"]):
        return not any(token_matches_roots(token, MEANINGFUL_TOKEN_ROOTS) for token in tokens)
    return False


def build_clarification_reply(session: LiaSessionState) -> str:
    stage_replies = {
        "opening": [
            "Acho que nao consegui entender bem essa ultima mensagem. Pode me contar de outro jeito o que esta pesando agora?",
            "Ainda nao peguei bem o sentido do que voce quis dizer. Se ficar mais facil, voce pode escrever algo como 'estou ansioso ha dias' ou 'estou muito pressionado'.",
            "Quero te acompanhar direito. Se preferir, me diga so uma frase curta, como 'estou cansado', 'terminei um relacionamento' ou 'nao consigo dormir'.",
        ],
        "anxiety": [
            "Nao consegui pegar bem essa parte. Pode me dizer de outro jeito se isso pesa mais no corpo, nos pensamentos ou nos dois?",
            "Ainda nao entendi direito sua resposta. Se ajudar, voce pode escrever algo como 'meu corpo acelera' ou 'minha mente nao desliga'.",
            "Quero continuar com voce sem adivinhar nada. Se preferir, responda com uma frase curta como 'sinto o corpo tenso' ou 'fico preocupado o tempo todo'.",
        ],
        "mood": [
            "Nao consegui entender bem essa parte. Pode me contar de outro jeito como ficaram seu sono, sua energia ou seu humor?",
            "Ainda nao peguei direito o que voce quis dizer. Se ajudar, voce pode escrever algo como 'estou dormindo mal' ou 'estou sem energia'.",
            "Quero te ouvir sem forcar uma resposta. Se preferir, me diga so uma frase curta como 'ando desanimado' ou 'meu sono piorou'.",
        ],
        "closing": [
            "Nao consegui entender bem essa ultima parte. Pode me contar de outro jeito o que ainda faltou dizer?",
            "Ainda nao peguei direito sua ultima mensagem. Se ajudar, escreva de forma simples o que continua mais pesado agora.",
            "Quero fechar esse check-in de um jeito fiel ao que voce sente. Se preferir, me diga em uma frase o que mais esta te pesando hoje.",
        ],
    }.get(
        session.stage,
        [
            "Nao consegui entender bem essa ultima parte. Pode me contar de outro jeito o que esta pesando agora?",
            "Ainda nao peguei bem o sentido do que voce quis dizer. Se ficar mais facil, escreva uma frase simples sobre como voce esta.",
            "Quero te acompanhar sem adivinhar. Se preferir, me diga em poucas palavras o que voce quer trazer agora.",
        ],
    )

    reply_index = min(max(session.clarification_streak - 1, 0), len(stage_replies) - 1)
    return stage_replies[reply_index]


def user_is_pointing_to_previous_message(user_message: str) -> bool:
    normalized = normalize_for_match(user_message)
    compact = re.sub(r"[^a-z ]", " ", normalized)
    return ("falei" in compact and ("ja" in compact.split() or "j" in compact.split())) or contains_any(
        normalized,
        [
            "mas eu ja falei",
            "eu ja falei",
            "ja falei",
            "acabei de falar",
            "foi isso que eu falei",
        ],
    )


def build_previous_message_ack_reply(session: LiaSessionState) -> str:
    previous_user_messages = [
        normalize_optional_text(item.content)
        for item in session.transcript[:-1]
        if item.role == "user" and normalize_optional_text(item.content)
    ]
    recent_user_context = " ".join(previous_user_messages[-3:])
    relevant_message = choose_relevant_previous_user_message(session, previous_user_messages)
    relevant_context = build_lia_context(session, relevant_message or recent_user_context)

    if relevant_context["light_topic"] or contains_any(
        normalize_for_match(relevant_message or recent_user_context),
        ["modelo", "modelar", "historia", "historias", "criei", "pego alguns momentos"],
    ):
        if contains_any(normalize_for_match(recent_user_context), ["saudade", "saudades"]):
            return (
                "Voce tem razao, a saudade apareceu justamente porque voce esta pegando momentos da sua vida e transformando isso em historia. "
                "Faz sentido seguir por ai: quando voce coloca essas lembrancas na historia, elas ficam mais leves, mais doloridas ou mais vivas pra voce?"
            )
        return (
            "Voce tem razao, voce ja explicou essa parte. "
            f"Eu vou seguir a partir disso: \"{(relevant_message or recent_user_context)[:140]}\". "
            "O que voce queria que essa historia conseguisse mostrar de voce ou desses momentos?"
        )

    if relevant_context["social_withdrawal"] or relevant_context["alone_burden"]:
        return (
            "Voce tem razao, voce ja trouxe isso. Eu vou considerar essa parte: "
            f"\"{(relevant_message or recent_user_context)[:140]}\". "
            "O que mais pesa nisso para voce: a vontade de se aproximar de alguem, o medo de ficar sozinho ou a dificuldade de comecar a falar?"
        )

    if relevant_message:
        return (
            "Voce tem razao, voce ja trouxe isso. Eu vou considerar essa parte: "
            f"\"{relevant_message[:140]}\". "
            "O que parece mais importante olhar agora dentro disso?"
        )

    return (
        "Voce tem razao em me chamar nisso. Vou tentar acompanhar melhor: "
        "qual parte do que voce ja trouxe voce quer que eu considere primeiro?"
    )


def build_unsure_reply(session: LiaSessionState) -> str:
    stage_replies = {
        "support": [
            "Tudo bem nao saber dizer agora. Se ficar mais facil, voce pode escolher uma dessas: foi mais cansaco, frustracao ou vontade de se afastar um pouco.",
            "Sem problema. Se quiser, me responde do jeito mais simples: isso teve mais cara de cansaco, chateacao ou pressao?",
        ],
        "anxiety": [
            "Tudo bem nao conseguir explicar de cara. Se ajudar, voce pode me dizer so qual chega mais perto: cabeca cheia, pressao por critica ou cansaco acumulado.",
            "Sem problema. Pode escolher so uma direcao pra gente continuar: isso parece mais frustracao, preocupacao ou desgaste?",
        ],
        "mood": [
            "Tudo bem se isso ainda estiver meio embaralhado. Se ficar mais facil, voce pode me dizer se foi mais cansaco, desanimo ou irritacao.",
            "Sem problema. Se quiser, escolhe so o que chega mais perto agora: falta de energia, vontade de sumir um pouco ou chateacao.",
        ],
        "closing": [
            "Tudo bem nao fechar isso certinho agora. Se quiser, me deixa so uma pista: foi mais cansaco, pressao ou tristeza?",
        ],
    }
    options = stage_replies.get(session.stage) or stage_replies["support"]
    reply_index = min(max(session.clarification_streak - 1, 0), len(options) - 1)
    return options[reply_index]


def should_offer_pause(session: LiaSessionState, context: dict[str, Any]) -> bool:
    return bool(context["unsure"] and not session.pause_used and not session.pause_offer_pending)


def build_pause_offer_reply(session: LiaSessionState) -> str:
    light_value = normalize_optional_text(session.memory.light_prompt_value)
    if not light_value:
        return "Se voce quiser, eu posso mudar um pouco o rumo por alguns segundos com uma pergunta bem leve. Quer?"

    if "filme" in light_value or "serie" in light_value:
        return "Se voce quiser, eu posso mudar um pouco de assunto e te perguntar uma coisa de filmes e series, tipo anime, comedia ou algo que te prende facil. Pode ser?"
    if "musica" in light_value:
        return "Se voce quiser, eu posso mudar um pouco de assunto e te perguntar uma coisa de musica, tipo o que voce mais curte ouvir. Pode ser?"
    if "esporte" in light_value:
        return "Se voce quiser, eu posso mudar um pouco de assunto e te perguntar uma coisa de esporte, so pra dar uma respirada. Pode ser?"
    if "comida" in light_value:
        return "Se voce quiser, eu posso mudar um pouco de assunto e te perguntar uma coisa de comida, so pra dar uma respirada. Pode ser?"
    return f"Se voce quiser, eu posso mudar um pouco de assunto e te perguntar uma coisa sobre {light_value}. Pode ser?"


def build_pause_message(session: LiaSessionState) -> str:
    light_value = normalize_optional_text(session.memory.light_prompt_value)
    if light_value:
        if "filme" in light_value or "serie" in light_value:
            return "Voce tinha escolhido filmes e series. O que te prende mais facil nisso: anime, suspense, comedia ou outra coisa?"
        if "musica" in light_value:
            return "Voce tinha escolhido musica. O que voce mais curte nela: letra, ritmo, artista ou o clima que ela cria?"
        if "esporte" in light_value:
            return "Voce tinha escolhido esporte. O que te prende mais nisso: assistir, jogar ou acompanhar um time?"
        if "comida" in light_value:
            return "Voce tinha escolhido comida. Tem alguma que sempre melhora um pouco o seu dia?"
        return (
            f"Voce tinha escolhido {light_value}. O que mais te prende nisso?"
        )
    return "Entao vamos por uma coisa simples: teve algo pequeno hoje que te deu um pouco de alivio?"


def build_pause_decline_reply(session: LiaSessionState) -> str:
    return "Tudo bem. A gente segue sem mudar o assunto. Se quiser, pode me responder do jeito mais simples que vier."


def build_post_pause_reply(session: LiaSessionState, user_message: str) -> str:
    normalized_message = normalize_for_match(user_message)
    light_value = normalize_optional_text(session.memory.light_prompt_value)

    if light_value and ("filme" in light_value or "serie" in light_value):
        if "anime" in normalized_message:
            return "Boa. Anime pode abrir um respiro mesmo. Se quiser, a gente volta para o que estava pesando antes."
        return "Esse assunto parece te prender com facilidade. Se quiser, a gente volta para o que estava pesando antes."

    if light_value and "musica" in light_value:
        return "Musica costuma abrir um respiro rapido mesmo. Se quiser, a gente volta para o que estava pesando antes."

    return "Bom ter um assunto mais leve no meio disso. Se quiser, a gente volta para o que estava pesando antes."


def is_affirmative_pause_reply(context: dict[str, Any]) -> bool:
    return bool(context["short_yes"] or contains_exact_phrase(context["latest_text"], ["quero", "pode", "pode sim", "sim quero"]))


def get_recent_transcript_by_role(
    session: LiaSessionState,
    role: Literal["assistant", "user"],
    limit: int = 3,
) -> list[str]:
    return [item.content for item in session.transcript if item.role == role][-limit:]


def latest_assistant_message(session: LiaSessionState) -> str | None:
    for item in reversed(session.transcript):
        if item.role == "assistant":
            return item.content
    return None


def latest_previous_user_message(session: LiaSessionState) -> str | None:
    for item in reversed(session.transcript[:-1]):
        if item.role == "user":
            return item.content
    return None


def choose_relevant_previous_user_message(session: LiaSessionState, messages: list[str]) -> str | None:
    latest_assistant = normalize_for_match(latest_assistant_message(session) or "")
    normalized_messages = [(message, normalize_for_match(message)) for message in reversed(messages)]

    if contains_any(latest_assistant, ["o que esta fazendo", "o que voce esta fazendo"]):
        for message, normalized in normalized_messages:
            if contains_any(normalized, ["modelo", "modelar", "criei", "historia", "historias", "pego alguns momentos"]):
                return message

    for message, normalized in normalized_messages:
        if contains_any(normalized, ["modelo", "modelar", "criei", "historia", "historias", "pego alguns momentos"]):
            return message

    return messages[-1] if messages else None


def question_was_recently_used(session: LiaSessionState, question: str) -> bool:
    normalized_question = normalize_for_match(question)
    recent_assistant_messages = get_recent_transcript_by_role(session, "assistant", limit=4)
    return any(normalized_question in normalize_for_match(message) for message in recent_assistant_messages)


def first_fresh_question(session: LiaSessionState, options: list[str]) -> str:
    for option in options:
        if not question_was_recently_used(session, option):
            return option
    return options[0]


def first_fresh_phrase(session: LiaSessionState, options: list[str]) -> str:
    recent_assistant_messages = [
        normalize_for_match(message) for message in get_recent_transcript_by_role(session, "assistant", limit=4)
    ]
    for option in options:
        normalized_option = normalize_for_match(option)
        if not any(normalized_option in message for message in recent_assistant_messages):
            return option
    return options[0]


def phrase_from_text(text_value: str, options: list[str]) -> str:
    normalized = normalize_for_match(text_value)
    if not normalized:
        return options[0]
    index = sum(ord(char) for char in normalized) % len(options)
    return options[index]


def recent_assistant_starts_with(session: LiaSessionState, prefix: str, *, limit: int = 2) -> bool:
    normalized_prefix = normalize_for_match(prefix)
    return any(
        normalize_for_match(message).startswith(normalized_prefix)
        for message in get_recent_transcript_by_role(session, "assistant", limit=limit)
    )


def reduce_repeated_opening(session: LiaSessionState, reflection: str) -> str:
    if not reflection.startswith("Entendi."):
        return reflection
    if len(get_recent_transcript_by_role(session, "assistant", limit=6)) >= 1:
        without_prefix = re.sub(r"^Entendi\.\s*", "", reflection, count=1).strip()
        if without_prefix:
            return without_prefix
        return first_fresh_phrase(session, ["Certo.", "Estou acompanhando.", "Vamos por essa parte."])
    if not recent_assistant_starts_with(session, "Entendi."):
        return reflection
    without_prefix = re.sub(r"^Entendi\.\s*", "", reflection, count=1).strip()
    if without_prefix:
        return without_prefix
    return first_fresh_phrase(session, ["Certo.", "Estou acompanhando.", "Vamos por essa parte."])


def reduce_repeated_first_sentence(session: LiaSessionState, reply: str) -> str:
    cleaned_reply = reply.strip()
    match = re.match(r"^(.+?[.!?])\s+(.+)$", cleaned_reply)
    if not match:
        return cleaned_reply

    first_sentence = match.group(1).strip()
    rest = match.group(2).strip()
    normalized_first = normalize_for_match(first_sentence)
    if len(normalized_first) < 18:
        return cleaned_reply

    recent_assistant_messages = [
        normalize_for_match(message) for message in get_recent_transcript_by_role(session, "assistant", limit=3)
    ]
    if any(normalized_first in message for message in recent_assistant_messages):
        return rest
    return cleaned_reply


def remember_question_intent(session: LiaSessionState, intent: str) -> None:
    session.recent_question_intents = [*session.recent_question_intents[-4:], intent]


def recent_intent_count(session: LiaSessionState, intent: str) -> int:
    return sum(1 for item in session.recent_question_intents[-3:] if item == intent)


def update_topic_state(session: LiaSessionState, key: str, value: str | None, confidence: float = 0.7) -> None:
    if key not in session.topic_states:
        return
    cleaned = normalize_optional_text(value)
    if not cleaned:
        return
    session.topic_states[key] = LiaTopicState(
        filled=True,
        confidence=max(session.topic_states[key].confidence, confidence),
        value=cleaned,
    )


def infer_topic_states(session: LiaSessionState, user_message: str) -> None:
    context = build_lia_context(session, user_message)
    latest_text = normalize_optional_text(user_message)
    if not latest_text:
        return

    update_topic_state(session, "opening_state", latest_text, 0.6)

    if context["quick_pass"] or context["no_issue"] or context["wants_to_stop"]:
        if session.turn_count >= 1:
            update_topic_state(session, "user_summary", latest_text, 0.7)
        return

    current_topic = session.current_topic
    if current_topic == "distress_nature" and contains_any(
        context["latest_text"], ["ansiedade", "preocupacao", "cansaco", "desanimo", "irritacao", "pressao"]
    ):
        update_topic_state(session, "distress_nature", latest_text, 0.9)
    if current_topic == "distress_context" and contains_any(
        context["latest_text"],
        [
            "trabalho",
            "estudo",
            "faculdade",
            "rotina",
            "relacionamento",
            "corpo",
            "critica",
            "cobranca",
            "situacao especifica",
            "tarefa",
            "tarefas",
            "responsabilidade",
        ],
    ):
        update_topic_state(session, "distress_context", latest_text, 0.9)
    if current_topic == "functional_impact" and contains_any(
        context["latest_text"], ["sono", "energia", "vontade", "foco", "humor", "corpo"]
    ):
        update_topic_state(session, "functional_impact", latest_text, 0.9)
    if current_topic == "frequency_duration" and contains_any(
        context["latest_text"],
        [
            "hoje",
            "dias",
            "semanas",
            "meses",
            "todo dia",
            "quase sempre",
            "varia",
            "ultimamente",
            "faz tempo",
        ],
    ):
        update_topic_state(session, "frequency_duration", latest_text, 0.9)

    if not session.topic_states["main_focus"].filled and (
        context["work_study"]
        or context["pressure"]
        or context["ansiedade"]
        or context["tristeza"]
        or context["energia"]
        or context["interesse"]
        or contains_any(context["latest_text"], ["critic", "insuficiente", "cobranc", "sobrecarreg", "desanimo"])
    ):
        update_topic_state(session, "main_focus", latest_text, 0.8)

    nature_parts: list[str] = []
    if context["pressure"]:
        nature_parts.append("pressao")
    if context["ansiedade"]:
        nature_parts.append("ansiedade")
    if context["tristeza"] or context["interesse"]:
        nature_parts.append("desanimo")
    if context["energia"] or context["worn_out"]:
        nature_parts.append("cansaco")
    if context["irritabilidade"]:
        nature_parts.append("irritacao")
    if context["social_withdrawal"]:
        nature_parts.append("isolamento")
    if contains_any(context["latest_text"], ["insuficiente", "sem animo", "desanimo", "falta de animo", "me sentir pequeno"]):
        nature_parts.append("desanimo")
    if nature_parts:
        update_topic_state(session, "distress_nature", ", ".join(dict.fromkeys(nature_parts)), 0.8)
    elif contains_any(context["latest_text"], ["pressao", "preocupacao", "irritacao", "cansaco", "desanimo"]):
        update_topic_state(session, "distress_nature", latest_text, 0.7)

    context_parts: list[str] = []
    if context["work_study"]:
        context_parts.append("trabalho ou estudos")
    if context["social_withdrawal"]:
        context_parts.append("isolamento ou afastamento")
    if context["relationship"]:
        context_parts.append("relacionamentos")
    if contains_any(context["latest_text"], ["rotina", "dia a dia"]):
        context_parts.append("rotina")
    if contains_any(context["latest_text"], ["tarefa", "tarefas", "responsabilidade"]):
        context_parts.append("tarefas e responsabilidades")
    if contains_any(context["latest_text"], ["situacao especifica"]):
        context_parts.append("situacao especifica")
    if contains_any(context["latest_text"], ["corpo", "fisico"]):
        context_parts.append("corpo")
    if context["pressure"] and not context_parts:
        context_parts.append("rotina e cobranca")
    if context_parts:
        update_topic_state(session, "distress_context", ", ".join(dict.fromkeys(context_parts)), 0.75)
    elif contains_any(context["latest_text"], ["critic", "cobranc"]):
        update_topic_state(session, "distress_context", "criticas e cobranca", 0.7)

    impact_parts: list[str] = []
    if context["sono"]:
        impact_parts.append("sono")
    if context["energia"]:
        impact_parts.append("energia")
    if context["interesse"]:
        impact_parts.append("vontade")
    if context["tristeza"]:
        impact_parts.append("humor")
    if context["social_withdrawal"]:
        impact_parts.append("convivio")
    if context["concentracao"]:
        impact_parts.append("foco")
    if contains_any(context["latest_text"], ["corpo", "fisico"]):
        impact_parts.append("corpo")
    if impact_parts:
        update_topic_state(session, "functional_impact", ", ".join(dict.fromkeys(impact_parts)), 0.85)
    elif contains_any(context["latest_text"], ["insuficiente", "nao consigo", "sem animo", "sem vontade", "humor", "foco"]):
        update_topic_state(session, "functional_impact", latest_text, 0.7)

    if context["duration"]:
        update_topic_state(session, "frequency_duration", context["duration"], 0.8)
    elif contains_any(
        context["latest_text"],
        [
            "maior parte dos dias",
            "todo dia",
            "quase sempre",
            "faz tempo",
            "ultimamente",
            "varia bastante",
            "varia",
            "de vez em quando",
            "alguns dias sim",
            "depende do dia",
            "semana passada",
            "uns dias mais, outros menos",
        ],
    ):
        update_topic_state(session, "frequency_duration", latest_text, 0.75)

    if len(tokenize_for_match(latest_text)) >= 6:
        update_topic_state(session, "concrete_example", latest_text, 0.65)

    if session.turn_count >= 4 and len(tokenize_for_match(latest_text)) >= 5:
        update_topic_state(session, "user_summary", latest_text, 0.55)


TOPIC_FLOW = [
    "opening_state",
    "main_focus",
    "distress_nature",
    "distress_context",
    "functional_impact",
    "frequency_duration",
    "concrete_example",
    "user_summary",
]


def next_lia_topic(session: LiaSessionState) -> str:
    if recent_intent_count(session, "distress_nature") >= 2 and not session.topic_states["distress_nature"].filled:
        update_topic_state(session, "distress_nature", "nao especificado", 0.4)

    if recent_intent_count(session, "distress_context") >= 2 and not session.topic_states["distress_context"].filled:
        update_topic_state(session, "distress_context", "contexto nao identificado", 0.4)

    if (
        session.topic_states["main_focus"].filled
        and session.topic_states["distress_nature"].filled
        and session.topic_states["functional_impact"].filled
        and session.topic_states["frequency_duration"].filled
    ):
        if recent_intent_count(session, "concrete_example") >= 2 and not session.topic_states["concrete_example"].filled:
            update_topic_state(session, "concrete_example", "nao detalhado", 0.4)
        if recent_intent_count(session, "user_summary") >= 1 and not session.topic_states["user_summary"].filled:
            update_topic_state(session, "user_summary", "resumo breve pendente", 0.4)

    for topic in TOPIC_FLOW:
        if not session.topic_states[topic].filled:
            return topic
    return "closing"


def extract_duration_phrase(text_value: str) -> str | None:
    if contains_any(text_value, ["um mes", "1 mes", "ha um mes", "faz um mes", "mais de um mes"]):
        return "ha cerca de um mes"
    if contains_any(text_value, ["meses", "alguns meses", "ha meses", "faz meses"]):
        return "ha alguns meses"
    if contains_any(text_value, ["semanas", "algumas semanas", "ha semanas", "faz semanas"]):
        return "ha algumas semanas"
    if contains_any(text_value, ["dias", "alguns dias", "ha dias", "faz dias"]):
        return "ha alguns dias"
    if contains_any(text_value, ["hoje", "desde hoje"]):
        return "desde hoje"
    if contains_any(text_value, ["minutos", "alguns minutos", "por alguns minutos"]):
        return "por alguns minutos"
    return None


def build_lia_context(session: LiaSessionState, user_message: str) -> dict[str, Any]:
    recent_user_messages = [
        item
        for item in get_recent_transcript_by_role(session, "user", limit=6)
        if is_probably_meaningful_message(item)
    ][-4:]
    if is_probably_meaningful_message(user_message):
        if not recent_user_messages or recent_user_messages[-1].strip() != user_message.strip():
            recent_user_messages.append(user_message)
            recent_user_messages = recent_user_messages[-4:]
    combined_text = normalize_for_match(" ".join(recent_user_messages))
    latest_text = normalize_for_match(user_message)
    latest_trimmed = latest_text.strip()
    latest_compact = re.sub(r"[^a-z ]", "", latest_trimmed).strip()
    unwell = contains_any(
        latest_text,
        [
            "nao estou bem",
            "nao to bem",
            "nao estou muito bem",
            "nao estou me sentindo bem",
            "nao estou me sentindo muito bem",
            "nao me sinto bem",
            "nao me sinto muito bem",
            "nao ando bem",
            "nao ando muito bem",
            "nao estou legal",
            "nao to legal",
            "nao estou nada bem",
            "estou mal",
            "to mal",
            "ando mal",
        ],
    )
    positive = not unwell and not contains_any(
        latest_text,
        [
            "cansad",
            "sobrecarreg",
            "desanim",
            "triste",
            "ansios",
            "pressao",
            "mal",
            "sem vontade",
        ],
    ) and (
        contains_exact_phrase(
            latest_text,
            [
                "estou bem",
                "to bem",
                "estou ok",
                "tudo bem",
                "mais leve",
                "tranquilo",
                "tranquila",
                "em paz",
                "to melhor",
                "estou melhor",
            ],
        )
    )
    no_issue = contains_any(
        latest_text,
        [
            "nao tem nada pegando",
            "nao tem nada me pegando",
            "so quis passar aqui",
            "so queria passar aqui",
            "so passei aqui",
            "so vim ver",
            "so vim testar",
            "so pra ver como voce tava respondendo",
        ],
    )
    unsure = latest_compact in {
        "nao sei",
        "nao sei dizer",
        "sei la",
        "nao tenho certeza",
        "dificil dizer",
        "dificil explicar",
        "nao consigo explicar",
    }
    figurative_distress = contains_any(
        combined_text,
        [
            "cabeca vai explodir",
            "cabeca parece que vai explodir",
            "cabeca esta cheia",
            "cabeca ta cheia",
            "mente vai explodir",
            "mente esta cheia",
            "mente ta cheia",
            "vou explodir",
            "explodir de tanta coisa",
            "cabeca cheia",
            "mente cheia",
            "muitos problemas",
            "muita coisa para resolver",
            "muita coisa pra resolver",
            "nao dou conta",
            "nao estou dando conta",
            "nao to dando conta",
        ],
    )
    work_offense = contains_any(
        combined_text,
        [
            "ofensa",
            "ofensas",
            "xing",
            "humilh",
            "desrespeito",
            "ataque",
            "critica",
            "criticas",
        ],
    )
    recipe_request = contains_any(
        latest_text,
        [
            "quero uma receita",
            "me da uma receita",
            "me de uma receita",
            "passa a receita",
            "passa uma receita",
            "faz uma receita",
            "faca uma receita",
            "receita de",
            "macarronada",
            "bolonhesa",
            "modo de preparo",
            "ingredientes",
        ],
    )
    external_task_request = recipe_request or contains_any(
        latest_text,
        [
            "faz um codigo",
            "faca um codigo",
            "faz o codigo",
            "so faz o codigo",
            "codigo em python",
            "codigo javascript",
            "me ensina a programar",
            "resolva essa conta",
            "calcule uma conta",
            "qual e a capital",
            "previsao do tempo",
            "noticia de hoje",
        ],
    )
    study_test_context = contains_exact_phrase(
        combined_text,
        [
            "prova",
            "vestibular",
            "concurso",
            "faculdade",
            "estudo",
            "estudar",
            "atividade",
            "tarefa",
            "trabalho da escola",
        ],
    )
    learning_attention_context = contains_any(
        combined_text,
        [
            "atencao",

            "distra",
            "foco",
            "concentr",
            "ler",
            "leitura",
            "escrever",
            "escrita",
            "entender o que eu leio",
            "organizar",
            "organizacao",

            "barulho",
            "ouvir",
            "escutar",
        ],
    )
    asks_for_options = contains_any(
        latest_text,
        [
            "o que eu faco",

            "nao sei o que fazer",

            "como lidar",
            "como posso lidar",
            "me ajuda",
            "preciso de ajuda",
            "queria ajuda",
        ],
    )
    persistent_distress = bool(extract_duration_phrase(combined_text)) and (
        contains_any(combined_text, ["dias", "semanas", "mes", "meses", "ha ", "faz "])
        or contains_any(combined_text, ["sono", "dorm", "rotina", "trabalho", "estudo", "fome", "energia", "sem vontade"])
    )
    social_withdrawal = contains_any(
        combined_text,
        ["me isolo", "me isolei", "isolado", "isolada", "isolamento", "me afasto", "afastando", "evitado meus amigos"],
    )
    decision_doubt = contains_any(
        combined_text,
        [
            "duvida",
            "duvidas",
            "escolha",
            "escolhas",
            "decisao",
            "decisoes",
            "decidir",
            "nao consigo lidar",
            "me sinto perdida",
            "me sinto perdido",
            "estou perdida",
            "estou perdido",
        ],
    )

    return {
        "latest_text": latest_text,
        "combined_text": combined_text,
        "duration": extract_duration_phrase(combined_text),
        "latest_duration": extract_duration_phrase(latest_text),
        "asks_about_professional": contains_any(
            latest_text,
            [
                "psicologo",
                "psicologa",
                "terapia",
                "terapeuta",
                "doutor",
                "doutora",
                "consulta",
                "profissional",
            ],
        )
        and contains_any(latest_text, ["ajudar", "ajuda", "conversar", "falar", "atendimento", "triagem"]),
        "mentions_help": contains_any(
            latest_text,
            [
                "preciso de ajuda",
                "precisava de ajuda",
                "quero ajuda",
                "queria ajuda",
                "me ajuda",
                "preciso conversar",
                "queria conversar",
            ],
        ),
        "palpitacao": contains_any(combined_text, ["palpit", "coracao", "acelerado", "taquic", "peito", "respirar", "respiracao", "falta de ar"]),
        "ansiedade": contains_any(combined_text, ["ansiedade", "ansios", "nervos", "tenso", "panico", "preocup", "alerta"]),
        "pressure": contains_any(
            combined_text,
            [
                "pression",
                "cobranc",
                "cobrando",
                "me cobro",
                "cobrando demais",
                "muita exigencia",
                "muita demanda",
                "muita responsabilidade",
            ],
        ),
        "worn_out": contains_any(
            combined_text,
            [
                "me sentindo terminado",
                "me sinto terminado",
                "acabado",
                "esgotad",
                "sobrecarreg",
                "sem aguentar",
                "no limite",
                "cansado demais",
            ],
        ),
        "ending": contains_any(
            combined_text,
            [
                "terminei",
                "terminou",
                "termino",
                "tinha terminado",
                "terminado recentemente",
                "acabou",
                "fim",
                "separ",
                "rompi",
                "rompimento",
            ],
        ),
        "relationship": contains_any(combined_text, ["namoro", "relacionamento", "namorado", "namorada", "parceiro", "parceira", "casamento"]),
        "work_study": contains_any(combined_text, ["trabalho", "estudo", "faculdade", "prova", "prazo", "chefe", "empresa", "emprego", "servico"]),
        "work_offense": work_offense,
        "financial_pressure": contains_any(combined_text, ["conta", "contas", "boleto", "boletos", "pagar", "dinheiro", "divida", "dividas", "aluguel"]),
        "caregiving": contains_any(combined_text, ["filho", "filha", "crianca", "cuidar", "cuidado", "mae", "mãe", "sozinho com", "sozinha com"]),
        "alone_burden": contains_any(combined_text, ["sozinha", "sozinho", "sem ajuda", "sem apoio", "tudo sozinha", "tudo sozinho"]),
        "controlar": contains_any(combined_text, ["controlar", "nao consigo parar", "nao desligo", "nao para"]),
        "relaxar": contains_any(combined_text, ["relax", "desaceler", "acalmar", "respirar"]),
        "medo": contains_any(combined_text, ["medo", "algo ruim", "vai dar errado", "perder o controle"]),
        "sono": contains_any(combined_text, ["sono", "dormir", "dormido", "durmo", "dormi", "inson", "acordo", "acordando"]),
        "energia": contains_any(combined_text, ["energia", "cansad", "cansaco", "exaust", "sem energia", "fadiga"]),
        "tristeza": contains_any(combined_text, ["triste", "pra baixo", "sem esperanca", "vazio"]),
        "interesse": contains_any(combined_text, ["sem vontade", "sem animo", "desanim", "prazer", "nao tenho vontade"]),
        "concentracao": contains_any(combined_text, ["concentr", "foco", "focar", "estudar"]),
        "study_test_context": study_test_context,
        "learning_attention_context": learning_attention_context,
        "asks_for_options": asks_for_options,
        "persistent_distress": persistent_distress,
        "decision_doubt": decision_doubt,
        "irritabilidade": contains_any(combined_text, ["irrit", "raiva", "estress"]),
        "social_withdrawal": social_withdrawal,
        "positive": positive,
        "no_issue": no_issue,
        "unwell": unwell,
        "mixed_feeling": contains_any(latest_text, ["mais ou menos", "meio assim", "nem bem nem mal", "entre bem e mal"]),
        "figurative_distress": figurative_distress,
        "creative": not figurative_distress
        and not social_withdrawal
        and contains_exact_phrase(
            latest_text,
            ["flores", "flor", "ceu", "mar", "chuva", "vento", "sol", "silencio", "recolher", "quietude"],
        ),
        "recipe_request": recipe_request,
        "external_task_request": external_task_request,
        "light_topic": contains_any(
            f"{latest_text} {combined_text}",
            [
                "musica",
                "filme",
                "filmes",
                "serie",
                "series",
                "esporte",
                "comida",
                "livro",
                "livros",
                "historia",
                "historias",
                "personagem",
                "personagens",
                "mundo ficticio",
                "mundos ficticios",
                "aventura",
                "aventuras",
                "anime",
                "animes",
            ],
        ),
        "story_topic": contains_any(
            f"{latest_text} {combined_text}",
            [
                "historia",
                "historias",
                "conto",
                "contos",
                "personagem",
                "personagens",
                "mundo ficticio",
                "mundos ficticios",
                "lembranca",
                "lembrancas",
                "momento da minha vida",
                "momentos da minha vida",
            ],
        ),
        "quick_pass": contains_any(latest_text, ["rapidinho", "so quis passar", "so passei", "so passar por aqui", "so vim passar", "so vim aqui"]),
        "wants_to_stop": contains_any(
            latest_text,
            [
                "acho que ja estou bem por agora",
                "acho que estou bem por agora",
                "ja estou bem por agora",
                "por agora ta bom",
                "por agora esta bom",
                "quero parar por aqui",
                "podemos parar por aqui",
                "acho que ja deu por hoje",
            ],
        ),
        "asks_to_talk": contains_any(latest_text, ["quero conversar", "so queria conversar", "so quero conversar", "queria desabafar"]),
        "unsure": unsure,
        "short_yes": latest_compact in {"sim", "s", "isso", "por alguns minutos sim", "sim por alguns minutos"},
        "short_no": latest_compact in {"nao"},
        "short_both": latest_compact in {"os dois", "os dois juntos", "nos dois"},
        "short_body": latest_compact in {"no corpo", "mais no corpo"},
        "short_mind": latest_compact in {"na mente", "na cabeca", "nos pensamentos", "mais na mente"},
        "stuck_without_improvement": contains_any(
            latest_text,
            [
                "nao parece melhorar",
                "nao parecem melhorar",
                "nao melhora",
                "nao melhorou",
                "continua ruim",
                "continua igual",
                "ainda me sinto cansado",
                "ainda me sinto cansada",
            ],
        ),
    }


def capitalize_first(text_value: str) -> str:
    return text_value[:1].upper() + text_value[1:] if text_value else text_value


def build_opening_topic(context: dict[str, Any]) -> str:
    if context["positive"]:
        return "esse momento mais leve"
    if context["mixed_feeling"]:
        return "esse meio termo que apareceu agora"
    if context["figurative_distress"]:
        return "essa cabeca cheia"
    if context["irritabilidade"]:
        return "essa irritacao"
    if context["study_test_context"] and context["concentracao"]:
        return "essa dificuldade de focar nos estudos"
    if context["light_topic"]:
        return "esse assunto leve que voce trouxe"
    if context["creative"]:
        return "essa imagem que veio a voce"
    if context["ending"] and context["pressure"]:
        return "esse termino junto com toda essa pressao"
    if context["ending"]:
        return "esse termino"
    if context["palpitacao"]:
        return "esse aperto no corpo"
    if context["ansiedade"]:
        if "preocup" in context["latest_text"] and not contains_any(context["latest_text"], ["ansios", "nervos", "tenso", "panico"]):
            return "essa preocupacao"
        return "essa ansiedade"
    if context["concentracao"]:
        return "essa dificuldade de focar"
    if context["pressure"] and context["work_study"]:
        return "essa pressao no trabalho ou nos estudos"
    if context["pressure"]:
        return "essa pressao"
    if context["worn_out"]:
        return "esse desgaste"
    if context["tristeza"]:
        return "esse peso no seu humor"
    if context["interesse"]:
        return "esse desanimo"
    if context["sono"]:
        return "esse sono ruim"
    if context["sono"] or context["energia"]:
        return "o impacto disso no seu corpo"
    return "isso tudo"


def is_support_related_message(context: dict[str, Any]) -> bool:
    support_keys = [
        "asks_about_professional",
        "mentions_help",
        "palpitacao",
        "ansiedade",
        "pressure",
        "worn_out",
        "ending",
        "relationship",
        "work_study",
        "work_offense",
        "financial_pressure",
        "caregiving",
        "alone_burden",
        "figurative_distress",
        "controlar",
        "relaxar",
        "medo",
        "sono",
        "energia",
        "tristeza",
        "interesse",
        "concentracao",
        "irritabilidade",
        "social_withdrawal",
        "decision_doubt",
        "unwell",
        "mixed_feeling",
        "no_issue",
        "wants_to_stop",
        "asks_to_talk",
        "unsure",
        "stuck_without_improvement",
    ]
    return any(bool(context.get(key)) for key in support_keys)


def asks_about_lia_or_triage(context: dict[str, Any]) -> bool:
    latest_text = context["latest_text"]
    if mentions_existing_professional_context(latest_text):
        return False
    return contains_any(
        latest_text,
        [
            "o que voce faz",
            "como voce funciona",
            "como funciona a lia",
            "para que voce serve",
            "o que e a lia",
            "como funciona a triagem",
            "o que e triagem",
            "quem vai ver",
            "quem ve isso",
            "meus dados",
            "relatorio",
            "consulta",
            "psicologo",
            "psicologa",
            "profissional",
        ],
    )


def mentions_existing_professional_context(text_value: str) -> bool:
    return contains_any(
        text_value,
        [
            "meu psicologo",
            "minha psicologa",
            "meu terapeuta",
            "minha terapeuta",
            "conversei com meu psicologo",
            "conversei com minha psicologa",
            "falei com meu psicologo",
            "falei com minha psicologa",
            "meu psicologo me ajudou",
            "minha psicologa me ajudou",
        ],
    )


def latest_assistant_offered_triage(session: LiaSessionState) -> bool:
    latest_reply = normalize_for_match(latest_assistant_message(session) or "")
    return contains_any(latest_reply, ["triagem", "profissional", "atendimento", "consulta"]) and contains_any(
        latest_reply,
        ["voce gostaria", "gostaria de seguir", "seguir para", "conversar com um profissional", "ter um profissional"],
    )


def user_accepts_or_asks_triage_next_step(context: dict[str, Any]) -> bool:
    latest_text = context["latest_text"]
    latest_compact = re.sub(r"[^a-z0-9 ]", " ", latest_text).strip()
    return contains_any(
        latest_text,
        [
            "gostaria sim",
            "quero atendimento",
            "quero um atendimento",
            "quero falar com um profissional",
            "quero conversar com um profissional",
            "quero seguir para triagem",
            "quero a triagem",
            "pode ser a triagem",
            "aceito a triagem",
            "como funcionaria",
            "como funciona",
            "e agora",
            "qual o proximo passo",
            "proximo passo",
        ],
    ) or latest_compact in {"sim", "acho que sim", "quero", "pode ser", "pode"}


def user_explicitly_requests_professional_handoff(context: dict[str, Any]) -> bool:
    latest_text = context["latest_text"]
    return contains_any(
        latest_text,
        [
            "gostaria de atendimento com um profissional",
            "quero atendimento com um profissional",
            "queria atendimento com um profissional",
            "gostaria de falar com um profissional",
            "quero falar com um profissional",
            "queria falar com um profissional",
            "preciso falar com um profissional",
            "gostaria de conversar com um profissional",
            "quero conversar com um profissional",
            "queria conversar com um profissional",
            "seguir para atendimento",
            "seguir para triagem",
        ],
    )


def should_finish_for_triage_handoff(session: LiaSessionState, context: dict[str, Any]) -> bool:
    if user_explicitly_requests_professional_handoff(context):
        return True
    if not latest_assistant_offered_triage(session):
        return False
    return user_accepts_or_asks_triage_next_step(context)


def build_triage_handoff_reply(context: dict[str, Any]) -> str:
    if contains_any(context["latest_text"], ["como funciona", "como funcionaria", "e agora", "proximo passo"]):
        return (
            "Funciona assim: eu organizo o que apareceu aqui e te mostro os horarios disponiveis com um profissional. "
            "Voce escolhe um horario, e essa conversa vai como apoio inicial para a triagem. "
            "Voce nao precisa explicar tudo de novo nem chegar com as palavras perfeitas."
        )

    return (
        "Certo. Entao faz sentido seguir para uma triagem com um profissional. "
        "Eu vou deixar o que apareceu aqui organizado para facilitar esse primeiro contato. "
        "Voce escolhe um horario e pode chegar sem precisar ter tudo pronto para explicar."
    )


def is_probably_question_or_request(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    if "?" in text_value:
        return True
    return normalized.startswith(
        (
            "qual ",
            "quais ",
            "como ",
            "quando ",
            "onde ",
            "quem ",
            "por que ",
            "porque ",
            "me fala ",
            "me explica ",
            "me ensina ",
            "faz ",
            "crie ",
            "cria ",
            "resolva ",
            "calcule ",
        )
    )


def is_off_scope_message(context: dict[str, Any], user_message: str) -> bool:
    if context["external_task_request"]:
        return True

    if is_support_related_message(context) or context["light_topic"] or context["creative"]:
        return False

    latest_text = context["latest_text"]
    explicit_off_scope = contains_any(
        latest_text,
        [
            "codigo",
            "programacao",
            "python",
            "javascript",
            "html",
            "css",
            "matematica",
            "calcule",
            "quanto e",
            "capital da",
            "receita de",
            "previsao do tempo",
            "clima hoje",
            "noticia",
            "futebol",
            "jogo de hoje",
            "trabalho da faculdade",
            "tcc pra mim",
            "redacao",
        ],
    )
    return explicit_off_scope or (is_probably_question_or_request(user_message) and not asks_about_lia_or_triage(context))


def build_related_question_reply(session: LiaSessionState, context: dict[str, Any]) -> str | None:
    if mentions_existing_professional_context(context["latest_text"]):
        return None

    if context["asks_about_professional"]:
        return first_fresh_phrase(
            session,
            [
                (
                    "Pode ajudar, sim. Conversar com um profissional pode te ajudar a olhar para isso com mais calma, "
                    "organizar o que esta acontecendo e pensar em proximos passos. "
                    "Voce nao precisa chegar com tudo pronto; levar essa duvida para a consulta ja e um bom comeco."
                ),
                (
                    "Essa vergonha antes da consulta pode acontecer. Voce nao precisa chegar sabendo explicar tudo; "
                    "um profissional pode te ajudar justamente a organizar isso aos poucos."
                ),
                (
                    "Seu problema nao precisa estar perfeito ou grave o bastante para ser levado. "
                    "Se algo esta pesando em voce, ja e um motivo valido para conversar com o profissional."
                ),
            ],
        )

    if asks_about_lia_or_triage(context):
        return (
            "Eu posso te ajudar a organizar o que voce esta sentindo e, quando fizer sentido, encaminhar isso para a triagem. "
            "Nao substituo um profissional, mas posso deixar a conversa mais clara para voce chegar com menos peso."
        )

    return None


def build_off_scope_reply(session: LiaSessionState) -> str:
    if session.off_scope_count <= 1:
        return (
            "Isso foge um pouco do meu papel por aqui. Eu consigo te ajudar melhor com o que voce esta sentindo "
            "ou com algo que esteja pesando hoje."
        )
    if session.off_scope_count == 2:
        return (
            "Eu entendo a pergunta, mas preciso manter nossa conversa dentro do meu objetivo: apoio, bem-estar e triagem. "
            "Se quiser, a gente pode voltar para o que te trouxe aqui hoje."
        )
    return (
        "Parece que talvez esse nao seja o melhor momento para essa conversa. Vou manter esse limite por cuidado. "
        "Quando voce quiser falar sobre como esta se sentindo ou sobre a triagem, eu continuo com voce."
    )


def build_specific_off_scope_reply(session: LiaSessionState, context: dict[str, Any]) -> str | None:
    if context["recipe_request"]:
        if context["work_offense"]:
            return (
                "Eu nao consigo seguir por receita aqui. Posso continuar com voce no que apareceu sobre as ofensas "
                "no trabalho, ou a gente pode fazer uma pausa breve dentro da conversa."
            )
        if context["work_study"]:
            return (
                "Eu nao consigo seguir por receita aqui. Posso continuar com voce no que apareceu sobre o trabalho, "
                "ou a gente pode fazer uma pausa breve dentro da conversa."
            )
        return (
            "Eu nao consigo seguir por receita aqui. Meu papel e ficar no apoio, bem-estar e triagem. "
            "Se quiser, a gente volta para o que esta pesando hoje."
        )
    return None


def build_scope_guard_reply(session: LiaSessionState, user_message: str) -> str | None:
    if user_is_pointing_to_previous_message(user_message):
        session.clarification_streak = 0
        return build_previous_message_ack_reply(session)

    if is_noise_or_mocking_message(user_message):
        session.clarification_streak = min(int(session.clarification_streak or 0) + 1, 3)
        return build_clarification_reply(session)

    context = build_lia_context(session, user_message)
    related_reply = build_related_question_reply(session, context)
    if related_reply:
        session.off_scope_count = 0
        if session.current_topic == "main_focus":
            return related_reply + " Para eu te acompanhar agora, o que voce mais espera conseguir entender ou aliviar primeiro?"
        return related_reply

    if is_off_scope_message(context, user_message):
        session.off_scope_count = min(int(session.off_scope_count or 0) + 1, 5)
        specific_reply = build_specific_off_scope_reply(session, context)
        if specific_reply:
            return specific_reply
        return build_off_scope_reply(session)

    if not context["unsure"] and not is_probably_meaningful_message(user_message):
        session.clarification_streak = min(int(session.clarification_streak or 0) + 1, 3)
        return build_clarification_reply(session)

    session.off_scope_count = 0
    return None


def infer_recommended_stage(
    session: LiaSessionState,
    user_message: str,
    risk_level: Literal["none", "attention", "urgent"] = "none",
) -> Literal["support", "anxiety", "mood", "closing"]:
    if risk_level == "urgent":
        return "closing"

    context = build_lia_context(session, user_message)

    if context["positive"] or context["creative"]:
        return "support"

    if context["tristeza"] or context["interesse"] or context["sono"] or context["energia"] or context["stuck_without_improvement"]:
        return "mood"

    if context["study_test_context"] and context["concentracao"]:
        return "anxiety"

    if context["ansiedade"] or context["pressure"] or context["palpitacao"] or context["controlar"] or context["relaxar"] or context["medo"]:
        return "anxiety"

    return "support"


def looks_generic_reflection(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    generic_fragments = [
        "obrigada por me contar isso",
        "eu consigo perceber que tem sido desgastante",
        "entendi. quando isso se prolonga",
        "estou aqui com voce",
        "quero compreender isso melhor com voce",
        "isso que voce acabou de me contar parece estar pesando em voce",
    ]
    return any(fragment in normalized for fragment in generic_fragments)


def looks_generic_question(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    generic_fragments = [
        "isso esta mais forte so hoje ou ja vem pesando ha alguns dias",
        "quando isso aparece, fica dificil relaxar ou controlar a preocupacao",
        "e nesses dias, como ficaram seu sono e sua energia",
        "voce percebeu menos vontade de fazer as coisas ou se sentiu mais para baixo",
        "se voce pudesse resumir, o que mais esta pesando nisso agora",
    ]
    return any(fragment in normalized for fragment in generic_fragments)


def has_usable_assistant_reply(text_value: str, recent_assistant_messages: list[str]) -> bool:
    normalized = normalize_for_match(text_value).strip()
    if not normalized:
        return False

    if normalized in recent_assistant_messages:
        return False

    if looks_generic_reflection(text_value) and looks_generic_question(text_value):
        return False

    token_count = len(tokenize_for_match(text_value))
    if token_count < 4:
        return False

    return True


PASSIVE_LIA_REPLY_FRAGMENTS = [
    "estou aqui para ouvir",
    "estou aqui para apoiar",
    "estou aqui para te ouvir",
    "estou aqui para te apoiar",
    "estou aqui para escutar",
    "estou aqui para te escutar",
    "vou estar aqui para te escutar",
    "queremos estar aqui para te escutar",
    "queremos estar aqui para te ouvir",
    "qual e o melhor jeito para eu te ajudar",
    "como posso te ajudar",
    "nao posso ajudar",
]

SUPPORTIVE_VALIDATION_FRAGMENTS = [
    "entendo",
    "faz sentido",
    "deve estar",
    "isso pesa",
    "isso desgasta",
    "isso cansa",
    "isso mexe",
    "consigo imaginar",
    "imagino como",
    "nao precisa carregar isso sozinho",
    "nao precisa dar conta de tudo agora",
    "nao precisa explicar tudo de uma vez",
    "nao precisa resolver isso agora",
]

SUPPORTIVE_GROUNDING_FRAGMENTS = [
    "por agora",
    "se puder",
    "vamos por partes",
    "um passo de cada vez",
    "sem se cobrar",
    "nao precisa se cobrar",
    "fica comigo nessa parte",
    "eu fico com voce",
    "podemos olhar isso por partes",
    "respira",
    "solta o ar",
]

GUIDED_QUESTION_FRAGMENTS = [
    "mente",
    "corpo",
    "dias",
    "preocup",
    "relax",
    "sono",
    "energia",
    "vontade",
    "interesse",
    "humor",
    "medo",
    "tens",
    "cansaco",
    "ritmo",
    "automatico",
    "peso",
    "aperto",
    "frequencia",
    "desde quando",
]

WEAK_COACHING_QUESTION_FRAGMENTS = [
    "amanha",
    "atividade",
    "habito",
    "segredo",
    "tem tempo para",
    "fazer algo que o ajude",
    "fazer algo que te ajude",
    "qual e a coisa mais simples",
    "o que gostaria de fazer agora",
    "maior diversao",
    "quando nao esta preocupado",
    "o que voce pode fazer",
    "qual e o primeiro passo",
    "primeiro passo",
    "gostaria de dar",
    "o que voce costuma fazer",
    "o que voce faz",
    "como voce se sente em geral",
    "fonte de prazer",
    "o que te faz",
    "o que possa reviver",
    "um lugar onde voce possa relaxar",
    "qual e algo que voce tenha gostado",
    "o que esta fazendo ultimamente",
    "quais sao os momentos que voce mais aprecia",
    "projeto ou uma atividade",
]

THERAPEUTIC_STYLE_FRAGMENTS = [
    "sinto muito que esteja assim",
    "sinto muito que isso esteja",
    "tenta nao se cobrar",
    "nao precisa se cobrar",
    "na sua mente, no corpo ou nos dois",
    "na sua mente, no seu corpo ou nos dois",
    "na sua mente ou no seu corpo",
    "esse pode ser nosso primeiro cuidado",
    "eu fico com voce nessa parte",
]

MISREAD_CLEAR_MESSAGE_FRAGMENTS = [
    "nao sei bem o que isso significa para voce",
    "nao sei bem o que isso quer dizer para voce",
    "nao entendi bem o que isso significa para voce",
    "nao sei ao certo o que isso significa para voce",
]

MODEL_LEAK_FRAGMENTS = [
    "ultima mensagem do usuario",
    "resposta anterior da lia",
    "reescreva agora",
    "aqui vai uma resposta final",
    "aqui vai lia",
    "resposta final que",
]


def reply_has_therapeutic_style(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    return any(fragment in normalized for fragment in THERAPEUTIC_STYLE_FRAGMENTS)


def reply_looks_like_model_leak(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    return any(fragment in normalized for fragment in MODEL_LEAK_FRAGMENTS)


def reply_speaks_as_if_lia_feels_user_experience(user_message: str, text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    normalized_user = normalize_for_match(user_message)
    first_person_feeling_fragments = [
        "eu sinto que",
        "sinto que",
        "eu estou sentindo",
        "estou sentindo",
        "eu estava no",
        "eu estava na",
        "estivesse revivendo",
        "estou revivendo",
        "minha vida",
        "meu bem estar atual",
        "meu bem-estar atual",
    ]
    if not contains_any(normalized, first_person_feeling_fragments):
        return False

    if normalized.startswith("sinto que") and normalized_user.startswith("sinto que"):
        return True

    return contains_any(normalized, ["como se eu", "eu sinto que isso", "eu estava", "minha vida", "meu bem"])


def reply_misreads_clear_message(session: LiaSessionState, user_message: str, text_value: str) -> bool:
    context = build_lia_context(session, user_message)
    normalized_reply = normalize_for_match(text_value)
    normalized_user = normalize_for_match(user_message)

    clear_message = is_probably_meaningful_message(user_message) and not context["unsure"]
    if clear_message and contains_any(normalized_reply, MISREAD_CLEAR_MESSAGE_FRAGMENTS):
        return True

    if "cansad" in normalized_user and "voce se sente cansado" in normalized_reply:
        return True
    if "ansios" in normalized_user and "voce se sente ansioso" in normalized_reply:
        return True
    if "triste" in normalized_user and "voce se sente triste" in normalized_reply:
        return True
    if "voce tem uma pergunta para mim" in normalized_reply:
        return True
    if "tem uma pergunta para mim" in normalized_reply:
        return True
    if not context["concentracao"] and contains_any(normalized_reply, ["concentrar", "concentracao", "foco"]):
        return True
    if "mais doente" in normalized_reply:
        return True
    if re.search(r"\beu tambem\b", normalized_reply):
        return True
    if reply_speaks_as_if_lia_feels_user_experience(user_message, text_value):
        return True
    if reply_looks_like_model_leak(text_value):
        return True

    return False

DISTRESS_ASSUMPTION_FRAGMENTS = [
    "sinto muito",
    "que esteja assim",
    "que isso esteja acontecendo",
    "que voce esteja passando por isso",
    "desafiador",
    "pesando em voce",
    "nao e facil",
]

GENERIC_MINIMIZING_FRAGMENTS = [
    "e normal sentir-se",
    "e natural sentir-se",
    "isso e natural",
    "isso e normal",
    "normal ter dias assim",
    "normal ter dias desse jeito",
    "isso e normal",
    "de vez em quando",
    "isso acontece",
    "todo mundo passa",
]

WEAK_COACHING_REPLY_FRAGMENTS = [
    "video engracado",
    "algo divertido",
    "maior diversao",
    "primeiro pensamento",
    "segredo para manter",
    "vou dar um conselho",
    "vou sugerir",
    "pense em uma coisa simples",
    "tome um cafe",
    "tome um cha",
    "caminhada ao ar livre",
    "boa refeicao",
    "anote",
    "registre o seu padrao",
    "plano para hoje",
    "semana que vem",
    "celebrar isso",
    "isso e um excelente comeco",
    "muita gente enfrentou problemas semelhantes",
    "isso ja e uma vitoria",
    "muito comum",
    "grande obstaculo",
    "desafio grande",
    "causando mais dor",
    "causando mais ansiedade",
    "controle sobre sua vida",
    "sobre sua vida",
    "e importante que voce encontre",
    "encontre maneira",
    "encontrar maneira",
    "para nao afetar sua saude emocional",
    "saude emocional",
    "correndo maratona",
    "recarregar as baterias",
    "o que me faz pensar",
    "pode ser uma semana dificil",
    "voce tem uma pergunta para mim",
    "tem uma pergunta para mim",
    "alguma pergunta para mim",
    "mais doente",
    "um pouco mais doente",
    "eu tambem",
    "ultimamente eu",
]

UNSUPPORTIVE_SOCIAL_PROOF_FRAGMENTS = [
    "muita gente",
    "todo mundo",
    "outras pessoas",
]

SYMBOLIC_OVERREAD_FRAGMENTS = [
    "muita chuva e silencio",
    "isso parece pesado",
    "isso esta pesado",
    "isso tudo",
    "sofrimento",
    "dor ai",
]

POSITIVE_QUICK_PASS_FRAGMENTS = [
    "rapidinho",
    "passar por aqui",
    "porta aberta",
    "quando quiser voltar",
    "quando quiser",
    "se quiser voltar",
    "respiro",
    "sem procurar problema",
]


def user_needs_active_guidance(session: LiaSessionState, user_message: str) -> bool:
    context = build_lia_context(session, user_message)
    latest_text = context["latest_text"]
    return (
        context["unwell"]
        or context["mentions_help"]
        or context["ansiedade"]
        or context["tristeza"]
        or context["interesse"]
        or context["sono"]
        or context["energia"]
        or context["pressure"]
        or context["worn_out"]
        or context["palpitacao"]
        or context["stuck_without_improvement"]
        or contains_any(
            latest_text,
            [
                "nao estou bem",
                "nao to bem",
                "nao estou muito bem",
                "nao estou me sentindo bem",
                "nao estou me sentindo muito bem",
                "nao me sinto bem",
                "nao me sinto muito bem",
                "nao ando bem",
                "nao ando muito bem",
                "nao estou legal",
                "nao to legal",
                "nao estou nada bem",
                "estou mal",
                "to mal",
                "ando mal",
                "ando cansado",
                "ando cansada",
                "sem vontade",
                "sem animo",
            ],
        )
    )


def reply_shows_active_guidance(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    question_count = text_value.count("?")
    has_question = question_count == 1
    has_validation = contains_any(normalized, SUPPORTIVE_VALIDATION_FRAGMENTS)
    has_grounding = contains_any(normalized, SUPPORTIVE_GROUNDING_FRAGMENTS)
    is_passive = contains_any(normalized, PASSIVE_LIA_REPLY_FRAGMENTS)
    has_guided_question = contains_any(normalized, GUIDED_QUESTION_FRAGMENTS)
    has_weak_coaching_question = contains_any(normalized, WEAK_COACHING_QUESTION_FRAGMENTS)
    is_minimizing = contains_any(normalized, GENERIC_MINIMIZING_FRAGMENTS)
    has_weak_coaching_reply = contains_any(normalized, WEAK_COACHING_REPLY_FRAGMENTS)
    has_unsupportive_social_proof = contains_any(normalized, UNSUPPORTIVE_SOCIAL_PROOF_FRAGMENTS)
    return (
        not is_passive
        and not is_minimizing
        and not has_weak_coaching_reply
        and not has_unsupportive_social_proof
        and has_question
        and has_validation
        and has_grounding
        and has_guided_question
        and not has_weak_coaching_question
    )


def reply_shows_supportive_progress(text_value: str) -> bool:
    normalized = normalize_for_match(text_value)
    question_count = text_value.count("?")
    has_question = question_count == 1
    has_validation = contains_any(normalized, SUPPORTIVE_VALIDATION_FRAGMENTS)
    has_guided_question = contains_any(normalized, GUIDED_QUESTION_FRAGMENTS)
    is_passive = contains_any(normalized, PASSIVE_LIA_REPLY_FRAGMENTS)
    is_minimizing = contains_any(normalized, GENERIC_MINIMIZING_FRAGMENTS)
    has_weak_coaching_question = contains_any(normalized, WEAK_COACHING_QUESTION_FRAGMENTS)
    has_weak_coaching_reply = contains_any(normalized, WEAK_COACHING_REPLY_FRAGMENTS)
    has_unsupportive_social_proof = contains_any(normalized, UNSUPPORTIVE_SOCIAL_PROOF_FRAGMENTS)
    return (
        not is_passive
        and not is_minimizing
        and not has_weak_coaching_reply
        and not has_unsupportive_social_proof
        and has_question
        and has_validation
        and has_guided_question
        and not has_weak_coaching_question
    )


def reply_respects_support_context(session: LiaSessionState, user_message: str, text_value: str) -> bool:
    context = build_lia_context(session, user_message)
    normalized = normalize_for_match(text_value)
    question_count = text_value.count("?")

    if reply_looks_like_model_leak(text_value):
        return False

    if reply_speaks_as_if_lia_feels_user_experience(user_message, text_value):
        return False

    if question_count > 1 and (is_support_related_message(context) or context["figurative_distress"] or context["work_offense"]):
        return False

    if contains_any(normalized, WEAK_COACHING_QUESTION_FRAGMENTS + WEAK_COACHING_REPLY_FRAGMENTS):
        return False

    if context["quick_pass"]:
        if contains_any(normalized, DISTRESS_ASSUMPTION_FRAGMENTS) or contains_any(
            normalized, GENERIC_MINIMIZING_FRAGMENTS
        ):
            return False
        if (
            question_count > 0
            or contains_any(normalized, GUIDED_QUESTION_FRAGMENTS)
            or contains_any(normalized, WEAK_COACHING_QUESTION_FRAGMENTS)
            or contains_any(normalized, WEAK_COACHING_REPLY_FRAGMENTS)
        ):
            return False
        return contains_any(
            normalized,
            POSITIVE_QUICK_PASS_FRAGMENTS + ["que bom", "bom ler", "leve", "quando quiser", "volta quando quiser"],
        )

    if context["light_topic"]:
        if contains_any(normalized, DISTRESS_ASSUMPTION_FRAGMENTS + GUIDED_QUESTION_FRAGMENTS):
            return False
        if context["story_topic"] and contains_any(normalized, ["incomod", "estress", "peso grande", "pesando"]):
            return False
        if question_count > 1:
            return False
        return contains_any(
            normalized,
            [
                "musica",
                "filme",
                "serie",
                "esporte",
                "comida",
                "livro",
                "historia",
                "historias",
                "conto",
                "lembranca",
                "imagin",
                "curte",
                "gosta de ouvir",
            ],
        )

    if context["no_issue"]:
        if contains_any(normalized, DISTRESS_ASSUMPTION_FRAGMENTS) or contains_any(
            normalized, GENERIC_MINIMIZING_FRAGMENTS + GUIDED_QUESTION_FRAGMENTS
        ):
            return False
        return contains_any(
            normalized,
            ["tudo certo", "passar aqui", "quando quiser", "volta quando quiser", "respiro", "sem problema"],
        )

    if context["positive"]:
        if contains_any(normalized, DISTRESS_ASSUMPTION_FRAGMENTS) or contains_any(
            normalized, GENERIC_MINIMIZING_FRAGMENTS
        ):
            return False
        if question_count > 1:
            return False
        if contains_any(normalized, WEAK_COACHING_QUESTION_FRAGMENTS) or contains_any(
            normalized, WEAK_COACHING_REPLY_FRAGMENTS
        ):
            return False
        if context["quick_pass"]:
            if contains_any(normalized, GUIDED_QUESTION_FRAGMENTS):
                return False
            return contains_any(normalized, POSITIVE_QUICK_PASS_FRAGMENTS + ["que bom", "bom ler", "leve"])
        return contains_any(
            normalized,
            [
                "que bom",
                "bom ler",
                "rapidinho",
                "passar por aqui",
                "dividir mesmo assim",
                "leve",
                "respiro",
                "quando quiser",
            ],
        )

    if context["creative"]:
        if contains_any(normalized, DISTRESS_ASSUMPTION_FRAGMENTS) or contains_any(
            normalized, SYMBOLIC_OVERREAD_FRAGMENTS
        ):
            return False
        if question_count > 1:
            return False
        if contains_any(normalized, WEAK_COACHING_QUESTION_FRAGMENTS) or contains_any(
            normalized, WEAK_COACHING_REPLY_FRAGMENTS
        ):
            return False
        return contains_any(
            normalized,
            [
                "imagem",
                "calma",
                "silencio",
                "chuva",
                "te passa",
                "apareceu",
                "recolher",
                "lembranca",
                "te leva",
                "te lembra",
            ],
        )

    if context["latest_duration"] and contains_any(
        normalized,
        [
            "tempo estivesse passando",
            "tempo estava passando",
            "tempo diferente",
            "mais rapido",
            "mais devagar",
        ],
    ):
        return False

    if contains_any(
        normalized,
        [
            "ingredientes",
            "modo de preparo",
            "macarrao",
            "macarronada",
            "bolonhesa",
            "carne moida",
            "cebola picada",
            "cozinhe",
            "refogue",
        ],
    ):
        return False

    if context["figurative_distress"] and contains_any(
        normalized,
        [
            "nao precisa transformar isso em problema",
            "partir dessa imagem",
            "essa imagem apareceu",
        ],
    ):
        return False

    if context["ansiedade"]:
        if contains_any(
            normalized,
            [
                "voce esta ansioso ultimamente",
                "voce tem ansiedade ultimamente",
                "sua ansiedade ultimamente",
                "essa ansiedade ultimamente",
                "voce anda ansioso ultimamente",
                "voce vem ansioso ultimamente",
            ],
        ):
            return False
        if not (context["duration"] or context["latest_duration"]) and contains_any(
            normalized,
            [
                "voce tem ansiedade",
                "sua ansiedade vem",
                "sua ansiedade parece",
                "essa ansiedade vem",
                "essa ansiedade parece",
                "a ansiedade esta presente",
                "a ansiedade esta afetando",
            ],
        ):
            return False

    if context["study_test_context"] and contains_any(
        normalized,
        [
            "voce tem tdah",
            "voce pode ter tdah",
            "voce tem dislexia",
            "voce pode ter dislexia",
            "voce tem tpac",
            "voce pode ter tpac",
        ],
    ):
        return False

    if (is_support_related_message(context) or context["figurative_distress"] or context["work_offense"]) and question_count == 0:
        if not contains_any(
            normalized,
            [
                "podemos parar",
                "podemos fechar",
                "por aqui",
                "triagem",
                "continuar comigo",
                "eu sigo com voce",
                "nao consigo seguir",
                "foge um pouco do meu papel",
            ],
        ):
            return False

    return True


def build_contextual_reflection(
    session: LiaSessionState,
    user_message: str,
    risk_level: Literal["none", "attention", "urgent"],
) -> str:
    context = build_lia_context(session, user_message)
    duration = context["duration"]

    if risk_level == "urgent":
        return "Isso parece serio. O mais importante agora e a sua seguranca."

    if context["no_issue"]:
        return "Tudo certo."

    if context["wants_to_stop"]:
        return "Entendi."

    if session.turn_count == 1 and context["positive"]:
        return "Que bom ler isso."

    if context["quick_pass"] and context["positive"]:
        return "Que bom ler isso."

    if session.turn_count == 1 and context["mixed_feeling"]:
        return "Entendi. Parece um daqueles dias em que voce nao esta mal de um jeito claro, mas tambem nao esta leve."

    if context["unsure"]:
        return "Tudo bem. Nem sempre isso vem claro na hora."

    if session.turn_count == 1 and context["story_topic"]:
        return "Pode ser do seu jeito. A gente comeca por uma parte pequena."

    if session.turn_count == 1 and context["light_topic"]:
        return "Claro. A gente pode falar disso sim."

    if session.turn_count == 1 and context["creative"]:
        return "Isso soa delicado."

    if context["mentions_help"] and session.turn_count == 1:
        return "Tudo bem falar disso aqui. A gente pode ir por partes."

    if session.turn_count == 1 and context["figurative_distress"]:
        return "Pelo que voce descreve, tem muita coisa disputando espaco na sua cabeca agora."

    if session.turn_count == 1 and context["financial_pressure"] and context["caregiving"]:
        if context["alone_burden"]:
            return "Contas para pagar, cuidado com filho e essa sensacao de estar sozinha nisso tudo formam uma carga bem grande."
        return "Lidar com contas e cuidado com filho ao mesmo tempo pode virar uma carga grande."

    if session.turn_count == 1 and context["ending"] and context["pressure"]:
        return "Entendi. Termino e pressao ao mesmo tempo costumam embaralhar bastante as coisas."

    if session.turn_count == 1 and context["ending"]:
        return "Entendi. Um termino mexe com muita coisa, mesmo quando a pessoa tenta seguir."

    if session.turn_count == 1 and context["pressure"] and context["worn_out"]:
        return phrase_from_text(
            user_message,
            [
                "Parece que voce ja vem segurando isso ha tempo e chegou cansado.",
                "Essa cobranca veio junto com um desgaste que nao parece pequeno.",
                "Da para sentir que essa pressao ja esta cobrando bastante de voce.",
            ],
        )

    if session.turn_count == 1 and context["pressure"]:
        return phrase_from_text(
            user_message,
            [
                "Essa pressao parece estar ocupando bastante espaco no seu dia.",
                "Essa cobranca chegou forte no jeito como voce esta passando por esse momento.",
                "Pelo que voce trouxe, esse comeco veio com uma carga grande em cima de voce.",
                "Tem uma pressao importante aparecendo nessa mudanca que voce contou.",
            ],
        )

    if session.turn_count == 1 and context["worn_out"]:
        return "Entendi. Parece que voce chegou bem no limite nesses ultimos dias."

    if session.turn_count == 1 and context["ansiedade"] and "preocup" in context["latest_text"] and not contains_any(
        context["latest_text"], ["ansios", "nervos", "tenso", "panico"]
    ):
        return "Essa preocupacao esta ocupando espaco na sua fala agora."

    if session.turn_count == 1 and context["ansiedade"]:
        return "Ansiedade pode aparecer de jeitos diferentes, entao eu prefiro entender como ela chega para voce."

    if session.turn_count == 1 and context["tristeza"]:
        return "Entendi. Tem um peso ai que nao parece pequeno."

    if session.turn_count == 1 and not session.memory.is_first_contact and session.memory.recent_summary:
        return "Obrigada por retomar isso comigo. A gente pode seguir daqui com calma."

    if context["latest_duration"] == "por alguns minutos" and context["palpitacao"]:
        return "Entendi. Entao, quando isso acontece, seu corpo leva alguns minutos para voltar ao ritmo normal."

    if context["short_yes"] and context["palpitacao"] and (context["relaxar"] or context["controlar"]):
        return "Entendi. Entao, quando isso vem, voce leva um tempo para conseguir desacelerar."

    if context["short_no"] and context["palpitacao"]:
        return "Entendi. Entao o desconforto parece ficar mais no corpo do que em uma preocupacao continua."

    if context["palpitacao"] and duration:
        return f"Entendi. Sentir o coracao acelerar assim {duration} deve ser bem cansativo."

    if context["palpitacao"]:
        return "Entendi. Sentir o coracao acelerar desse jeito deve ser bem desconfortavel."

    if session.stage == "anxiety" and context["pressure"] and context["worn_out"]:
        return "Entendi. Parece que essa pressao toda ja esta te deixando bem esgotado."

    if session.stage == "anxiety" and context["pressure"]:
        return first_fresh_phrase(
            session,
            [
                "Entendi. Essa pressao parece estar cobrando um preco ai.",
                "Entendi. Isso soa como algo que foi pesando aos poucos.",
                "Entendi. Quando isso vai acumulando, uma hora aparece de algum jeito.",
            ],
        )

    if session.stage == "anxiety" and context["worn_out"]:
        return "Entendi. Isso soa como um desgaste de quem ja vem segurando muita coisa."

    if session.stage == "anxiety" and (context["controlar"] or context["relaxar"]):
        return "Entendi. Parece que, quando isso aparece, nao e simples recuperar o ritmo."

    if session.stage == "anxiety" and context["medo"]:
        return "Entendi. Parece que tem um medo aparecendo ai, mas quero confirmar com calma como isso chega para voce."

    if context["work_offense"] and context["work_study"]:
        return "Entendi. Ofensas no trabalho podem mexer bastante com a forma como voce passa pelo dia."

    if session.stage == "mood" and context["sono"] and context["energia"]:
        return first_fresh_phrase(
            session,
            [
                "Obrigada por explicar melhor. Quando sono e energia sentem, o dia todo costuma pesar.",
                "Entendi. Quando sono e energia saem do lugar, o resto do dia costuma sentir junto.",
                "Entendi. Sono ruim e energia baixa acabam mexendo com tudo ao redor.",
            ],
        )

    if session.stage == "mood" and (context["tristeza"] or context["interesse"]):
        return first_fresh_phrase(
            session,
            [
                "Entendi. Isso parece estar alcancando tambem seu humor e sua disposicao.",
                "Entendi. Isso nao ficou so no cansaco; parece que bateu tambem no jeito de levar o dia.",
                "Entendi. Isso parece estar mexendo tambem com seu animo.",
            ],
        )

    if session.stage == "mood" and context["pressure"] and context["worn_out"]:
        return first_fresh_phrase(
            session,
            [
                "Entendi. Quando vai acumulando assim, o dia inteiro acaba sentindo junto.",
                "Entendi. Quando isso aperta por muito tempo, o corpo e o humor acabam entrando no meio.",
                "Entendi. Isso parece estar transbordando para o resto do dia.",
            ],
        )

    if session.stage == "support" and context["positive"]:
        return "Que bom saber disso."

    if session.stage == "support" and context["mixed_feeling"]:
        return "Entendi. Parece que o dia ficou num meio termo cansativo."

    if context["social_withdrawal"]:
        return first_fresh_phrase(
            session,
            [
                "Esse afastamento dos outros parece estar ficando importante nessa historia.",
                "Ficar se isolando depois pode pesar de um jeito silencioso.",
                "Essa vontade de se afastar tambem merece entrar no que a gente esta olhando.",
            ],
        )

    if context["decision_doubt"]:
        return first_fresh_phrase(
            session,
            [
                "Dificil decidir quando tudo fica meio embaralhado por dentro.",
                "Quando a cabeca fica assim, ate explicar a duvida ja pode ser confuso.",
                "Da para comecar sem saber exatamente qual e a escolha ainda.",
            ],
        )

    if session.stage == "support" and context["light_topic"]:
        return "Pode me contar por onde voce quer comecar nesse assunto."

    if session.stage == "support" and context["creative"]:
        return "Gostei dessa imagem que veio agora."

    if duration and session.turn_count > 1:
        return first_fresh_phrase(
            session,
            [
                f"Entendi. Levar isso {duration} realmente desgasta.",
                f"Entendi. Estar com isso {duration} ja pesa de outro jeito.",
                f"Entendi. Quando isso vem acontecendo {duration}, e natural que va cansando.",
            ],
        )

    if session.turn_count == 1:
        topic = capitalize_first(build_opening_topic(context))
        if context["positive"] or context["creative"]:
            return f"Entendi. {topic} parece importante para voce agora."
        return f"Entendi. {topic} parece estar pesando em voce."

    return "Entendi."


def build_contextual_question(
    session: LiaSessionState,
    user_message: str,
    stage: Literal["support", "anxiety", "mood", "closing"],
) -> str | None:
    context = build_lia_context(session, user_message)
    topic = session.current_topic

    if context["wants_to_stop"]:
        remember_question_intent(session, "closing")
        return "Podemos fechar por aqui hoje, se voce quiser."

    if context["quick_pass"] or context["no_issue"]:
        remember_question_intent(session, "closing")
        return "Podemos deixar por aqui hoje, se voce quiser."

    if context["positive"]:
        remember_question_intent(session, "closing")
        return "Pode deixar esse dia mais tranquilo ser so um respiro por aqui."

    if context["asks_for_options"] and (
        count_meaningful_user_messages(session) >= 3
        or not (context["financial_pressure"] or context["caregiving"] or context["study_test_context"])
    ):
        remember_question_intent(session, "main_focus")
        return "Voce prefere que eu te ajude a organizar o que esta sentindo, pensar em um proximo passo simples ou so separar melhor essa pressao? Se fizer sentido, tambem posso te recomendar para um profissional. O que acha?"

    if context["persistent_distress"] and count_meaningful_user_messages(session) >= 3:
        remember_question_intent(session, "closing")
        return "Pelo que voce trouxe, isso ja vem de outros dias e esta atrapalhando sua rotina. Voce gostaria de seguir para uma triagem com um profissional?"

    if context["study_test_context"] and (context["learning_attention_context"] or context["concentracao"]):
        if not contains_any(context["latest_text"], ["prova", "estudo", "estudar", "faculdade"]):
            return None
        remember_question_intent(session, "distress_context")
        return first_fresh_question(
            session,
            [
                "Isso acontece so nessa prova ou voce tambem percebe dificuldade de atencao, leitura ou organizacao em outros momentos?",
                "Quando voce tenta estudar, o que pesa mais: a ansiedade da prova, manter o foco ou entender o conteudo?",
                "Essa tensao aparece mais pelo resultado da prova ou por alguma dificuldade para se concentrar, ler ou organizar os estudos?",
            ],
        )

    if topic == "closing":
        remember_question_intent(session, "closing")
        if context["quick_pass"] or context["positive"]:
            return "Podemos parar por aqui hoje, se voce quiser."
        return "Acho que ja consegui montar um retrato bom do que apareceu hoje. Quer encerrar por aqui?"

    if topic == "main_focus":
        remember_question_intent(session, "main_focus")
        if context["story_topic"]:
            return first_fresh_question(
                session,
                [
                    "Do que e essa historia, pelo menos do jeito que ela aparece para voce agora?",
                    "Essa historia e mais um conto inventado, uma lembranca sua ou uma mistura das duas coisas?",
                    "Qual parte dessa historia veio mais forte na sua cabeca?",
                ],
            )
        if context["creative"] or context["light_topic"]:
            return first_fresh_question(
                session,
                [
                    "Por onde voce quer comecar nesse assunto?",
                    "O que mais te prende nisso agora?",
                    "Qual parte disso voce queria me contar primeiro?",
                ],
            )
        if context["palpitacao"]:
            return first_fresh_question(
                session,
                [
                    "Quando isso acontece, vem junto com falta de ar, aperto no peito ou medo de acontecer de novo?",
                    "Nesses momentos, o que chama mais sua atencao: o coracao acelerado, a respiracao ou o medo que vem junto?",
                    "Isso costuma passar em alguns minutos ou fica te acompanhando por mais tempo?",
                ],
            )
        if context["persistent_distress"] and count_meaningful_user_messages(session) >= 3:
            return "Pelo que voce trouxe, isso ja vem aparecendo ha alguns dias e merece cuidado. Voce gostaria que eu te ajudasse a seguir para uma triagem com um profissional?"
        if context["asks_for_options"]:
            return "Voce prefere que eu te ajude a organizar o que esta sentindo, pensar em um proximo passo simples ou so separar melhor essa pressao? Se fizer sentido, tambem posso te recomendar para um profissional. O que acha?"
        if context["decision_doubt"]:
            return first_fresh_question(
                session,
                [
                    "O que te faz sentir que nao consegue decidir direito agora?",
                    "Quando voce tenta pensar nisso, o que embaralha primeiro?",
                    "Tem alguma situacao puxando essa sensacao de duvida, ou ela vem mais geral?",
                ],
            )
        if context["work_offense"] and context["work_study"]:
            return first_fresh_question(
                session,
                [
                    "O que mais machuca nessas ofensas no trabalho: o que dizem, a frequencia ou a sensacao de ficar sem defesa?",
                    "Essas ofensas no trabalho acontecem mais com uma pessoa especifica ou no ambiente como um todo?",
                    "Quando essas ofensas acontecem, o que fica mais forte depois: tristeza, raiva ou medo de voltar para la?",
                ],
            )
        if context["figurative_distress"]:
            return first_fresh_question(
                session,
                [
                    "Se a gente for por partes, qual problema parece mais urgente agora?",
                    "Entre tudo que esta enchendo sua cabeca, o que mais precisa de cuidado primeiro?",
                    "O que mais pesa nessa sensacao de cabeca cheia: a quantidade de problemas, o medo de nao dar conta ou ter que resolver tudo sozinho?",
                ],
            )
        return first_fresh_question(
            session,
            [
                "O que mais ficou na sua cabeca hoje?",
                "Se tivesse que apontar uma coisa, o que mais pesou hoje?",
                "O que mais te pegou nesse dia?",
            ],
        )

    if topic == "distress_nature":
        remember_question_intent(session, "distress_nature")
        if context["ansiedade"]:
            return first_fresh_question(
                session,
                [
                    "Quando voce fala ansiedade, isso aparece mais como preocupacao, tensao no corpo ou dificuldade de se concentrar?",
                    "Para eu nao assumir errado: essa ansiedade vem mais nos pensamentos, no corpo ou na hora de tentar focar?",
                    "Essa ansiedade parece mais ligada a preocupacao, pressao ou medo de algo dar errado?",
                ],
            )
        return first_fresh_question(
            session,
            [
                "Isso tem mais cara de cansaco, pressao ou desanimo?",
                "Se voce fosse dar um nome pra isso agora, o que chegaria mais perto?",
                "O que parece mais forte nisso: preocupacao, cansaco ou falta de animo?",
            ],
        )

    if topic == "distress_context":
        remember_question_intent(session, "distress_context")
        if context["study_test_context"] and (context["ansiedade"] or context["pressure"] or context["concentracao"]):
            return first_fresh_question(
                session,
                [
                    "Isso acontece so nessa prova ou voce tambem percebe dificuldade de atencao, leitura ou organizacao em outros momentos?",
                    "Quando voce tenta estudar, o que pesa mais: a ansiedade da prova, manter o foco ou entender o conteudo?",
                    "Essa tensao aparece mais pelo resultado da prova ou por alguma dificuldade para se concentrar, ler ou organizar os estudos?",
                ],
            )
        if context["financial_pressure"] and context["caregiving"]:
            return first_fresh_question(
                session,
                [
                    "Se a gente for por partes, o que esta apertando mais agora: as contas, o cuidado com seu filho ou a sensacao de estar sozinha?",
                    "Entre dinheiro, cuidado com seu filho e essa sensacao de carregar tudo, qual parte esta mais urgente hoje?",
                    "O que parece pesar primeiro quando voce pensa nisso tudo: pagar as contas, cuidar do seu filho ou nao ter apoio suficiente?",
                ],
            )
        if context["work_offense"] and context["work_study"]:
            return first_fresh_question(
                session,
                [
                    "Essas ofensas no trabalho acontecem mais com uma pessoa especifica ou no ambiente como um todo?",
                    "O que mais pesa nessas ofensas: ouvir aquilo, ter que continuar trabalhando depois ou sentir que ninguem segura junto?",
                    "Quando isso acontece no trabalho, voce costuma conseguir se proteger de algum jeito ou fica tendo que engolir tudo?",
                ],
            )
        if context["figurative_distress"]:
            return first_fresh_question(
                session,
                [
                    "Se a gente for por partes, o que esta mais urgente agora: os problemas para resolver, a sensacao de cabeca cheia ou algo que aconteceu hoje?",
                    "Quando sua cabeca fica assim, isso vem mais da quantidade de coisas para resolver ou de alguma situacao especifica?",
                    "Qual parte disso parece estar fazendo mais barulho agora?",
                ],
            )
        if context["financial_pressure"]:
            return first_fresh_question(
                session,
                [
                    "Quando voce pensa nessas contas, o que aperta mais: o valor, o prazo ou a sensacao de nao saber por onde comecar?",
                    "Essa preocupacao com dinheiro esta mais ligada ao que vence agora ou ao medo do que pode vir depois?",
                ],
            )
        if context["caregiving"]:
            return first_fresh_question(
                session,
                [
                    "No cuidado com seu filho, qual parte tem pesado mais para voce agora?",
                    "Isso pesa mais pela responsabilidade do cuidado ou pela sensacao de ter pouco apoio?",
                ],
            )
        return first_fresh_question(
            session,
            [
                "Isso parece vir mais do trabalho, da rotina ou de alguma situacao especifica?",
                "Voce sente que isso tem mais a ver com o que esta acontecendo no seu dia ou com algo que ja vem se acumulando?",
                "Quando voce pensa nisso, o que mais aparece junto: rotina, cobranca ou alguma situacao concreta?",
            ],
        )

    if topic == "functional_impact":
        remember_question_intent(session, "functional_impact")
        return first_fresh_question(
            session,
            [
                "Onde isso mais bate em voce: sono, energia ou vontade?",
                "O que isso mais mexe no seu dia a dia agora?",
                "No fim das contas, isso pesa mais no seu corpo, na sua energia ou na sua vontade de fazer as coisas?",
            ],
        )

    if topic == "frequency_duration":
        remember_question_intent(session, "frequency_duration")
        if context["duration"] or context["latest_duration"] or session.topic_states["frequency_duration"].filled:
            if context["persistent_distress"]:
                return "Entendi. Como isso ja vem de outros dias, voce gostaria de continuar entendendo isso comigo ou prefere seguir para uma triagem com um profissional?"
            return "Entendi. Como isso ja vem de outros dias, o que mudou mais desde que comecou?"
        return first_fresh_question(
            session,
            [
                "Isso foi mais de hoje ou ja vem de outros dias?",
                "Tem quanto tempo que isso ta te acompanhando desse jeito?",
                "Isso aparece so em alguns momentos ou ja vem ficando frequente?",
            ],
        )

    if topic == "concrete_example":
        remember_question_intent(session, "concrete_example")
        return first_fresh_question(
            session,
            [
                "Teve alguma situacao recente que resume bem isso?",
                "Se voce quiser, me da um exemplo pequeno de quando isso bateu mais forte.",
                "Tem alguma cena do seu dia que mostra bem como isso apareceu?",
            ],
        )

    if topic == "user_summary":
        remember_question_intent(session, "user_summary")
        return first_fresh_question(
            session,
            [
                "Se eu fosse resumir o que voce me contou ate aqui, o que nao poderia faltar?",
                "Antes de fechar, tem alguma parte disso que voce acha importante nao deixar passar?",
                "O que voce gostaria que ficasse mais claro sobre esse momento?",
            ],
        )

    if context["unsure"]:
        return None

    if stage == "support":
        grounded_reply = build_grounded_lia_reply(session, user_message)
        if grounded_reply:
            return None
        if context["positive"]:
            return "Podemos deixar por aqui hoje, se voce quiser."
        if context["mixed_feeling"]:
            return "O que mais te pegou hoje?"
        if context["unwell"]:
            return "Se quiser, me conta o que mais te pegou hoje."
        if context["story_topic"]:
            return "Essa historia e mais um conto inventado, uma lembranca sua ou uma mistura das duas coisas?"
        if context["light_topic"]:
            return "O que voce mais curte nisso?"
        if context["creative"]:
            return "Flores te passam calma ou essa imagem apareceu por algum motivo especial?"
        if context["work_offense"] and context["work_study"]:
            return "O que mais machuca nessas ofensas no trabalho?"
        if context["figurative_distress"]:
            return "Se a gente for por partes, qual problema parece mais urgente agora?"
        if context["study_test_context"] and context["concentracao"] and contains_any(
            context["latest_text"], ["prova", "estudo", "estudar", "faculdade"]
        ):
            return "Quando voce tenta estudar, o que pesa mais: manter o foco, entender o conteudo ou pensar na prova?"
        if context["mentions_help"] or context["asks_to_talk"]:
            return "Quer me contar o que mais esta batendo forte ai agora?"
        if context["work_study"] and context["pressure"]:
            return "No meio desse trabalho todo, o que foi o que mais te desgastou?"
        if context["work_study"]:
            return "Quando voce fala de trabalho, foi mais volume, cobranca ou cansaco acumulado?"
        if context["pressure"]:
            return "Essa pressao apareceu mais como cobranca, cansaco ou cabeca cheia?"
        if session.turn_count == 1:
            return "Se quiser, me conta o que mais ficou na sua cabeca hoje."
        return default_next_question("support", session.turn_count)

    if stage == "anxiety":
        grounded_reply = build_grounded_lia_reply(session, user_message)
        if grounded_reply and session.turn_count > 1:
            return None
        if context["palpitacao"] and session.turn_count <= 4:
            return first_fresh_question(
                session,
                [
                    "Quando isso acontece, vem junto com falta de ar, aperto no peito ou medo de acontecer de novo?",
                    "Nesses momentos, o que chama mais sua atencao: o coracao acelerado, a respiracao ou o medo que vem junto?",
                    "Isso costuma passar em alguns minutos ou fica te acompanhando por mais tempo?",
                ],
            )
        if context["mentions_help"] and session.turn_count == 1:
            return "O que esta mais dificil nisso agora?"
        if session.turn_count == 1 and context["ending"] and context["pressure"]:
            return "Desde esse termino, o que mais tem pesado: a saudade, a ansiedade ou a pressao do dia a dia?"
        if session.turn_count == 1 and context["ending"]:
            return "Desde que isso aconteceu, o que mais tem pesado: saudade, ansiedade ou sensacao de vazio?"
        if session.turn_count == 1 and context["pressure"] and context["worn_out"]:
            return "Quando isso aperta, o que pesa mais pra voce?"
        if session.turn_count == 1 and context["pressure"]:
            if context["work_study"]:
                return "Essa pressao vem mais do trabalho, dos estudos ou da expectativa que colocam sobre voce?"
            return "Essa pressao aparece mais em que momento do seu dia?"
        if session.turn_count == 1 and context["worn_out"]:
            return "Esse cansaco tem mais cara de esgotamento, preocupacao ou um pouco dos dois?"
        if session.turn_count == 1 and context["ansiedade"]:
            if context["study_test_context"]:
                return "Essa ansiedade aparece mais na hora de estudar, na hora da prova ou quando voce pensa no resultado?"
            if "preocup" in context["latest_text"] and not contains_any(context["latest_text"], ["ansios", "nervos", "tenso", "panico"]):
                return "Essa preocupacao aparece mais como pensamento repetindo, tensao no corpo ou dificuldade de desligar?"
            return "Quando voce fala ansiedade, isso aparece mais como preocupacao, tensao no corpo ou dificuldade de se concentrar?"
        if session.turn_count == 1 and context["tristeza"]:
            return "O que mais tem vindo junto com isso?"
        if session.turn_count == 1 and not session.memory.is_first_contact:
            return "O que voce quer colocar primeiro hoje?"
        if context["short_both"] and session.turn_count <= 3:
            return "Quando os dois pesam juntos, o que costuma derrubar mais depois: o cansaco, o sono ruim ou a mente que nao desacelera?"
        if context["short_body"]:
            return "Quando isso pesa mais no corpo, vem como tensao, coracao acelerado ou cansaco logo depois?"
        if context["short_mind"]:
            return "Quando pesa mais na mente, vem como preocupacao constante, pensamentos acelerados ou medo de algo ruim?"
        if context["pressure"] and context["worn_out"]:
            return "No meio dessa pressao toda, o que mais te desgasta?"
        if context["pressure"]:
            return "Quando essa pressao aperta, como isso aparece mais pra voce?"
        if context["worn_out"]:
            return "Esse esgotamento aparece mais como cansaco, irritacao ou cabeca cheia?"
        if context["palpitacao"] and session.turn_count <= 2:
            return "Quando isso acontece, vem junto com medo, aperto no peito ou preocupacao dificil de desligar?"
        if context["latest_duration"] == "por alguns minutos" and context["palpitacao"]:
            return "Nesses minutos, pesa mais o coracao disparado ou o medo de que algo ruim possa acontecer?"
        if context["short_yes"] and (context["relaxar"] or context["controlar"]):
            return "Nesses minutos, pesa mais a sensacao no corpo ou o medo de que algo ruim aconteca?"
        if context["duration"] and not context["controlar"] and not context["medo"]:
            return "Isso costuma aparecer em momentos especificos ou pode surgir mesmo sem um gatilho claro?"
        if context["controlar"] or context["relaxar"]:
            return "Quando isso aparece, o que voce sente que muda primeiro?"
        if context["medo"]:
            return "Quando isso vem, parece que algo ruim pode acontecer?"
        if session.turn_count == 1:
            return "Se voce fosse resumir em uma frase, o que mais esta pesando nisso agora?"
        return default_next_question("anxiety", session.turn_count)

    if stage == "mood":
        grounded_reply = build_grounded_lia_reply(session, user_message)
        if grounded_reply and session.turn_count > 1:
            return None
        if context["stuck_without_improvement"]:
            return "Nesses dias sem melhora, o que tem te derrubado mais: cansaco, sono ruim ou falta de vontade?"
        if context["pressure"] and context["worn_out"] and not context["sono"] and not context["energia"]:
            return "Com essa pressao toda, como ficaram seu sono e sua energia nesses dias?"
        if context["palpitacao"] and not context["sono"] and not context["energia"]:
            return "Quando isso vai se repetindo, como ficam seu sono e sua energia nesses dias?"
        if not context["sono"] and not context["energia"]:
            return "E nisso tudo, como tem ficado seu sono e sua energia?"
        if context["sono"] and not context["energia"]:
            return "E alem do sono, sua energia durante o dia ficou mais baixa?"
        if context["energia"] and not context["interesse"]:
            return first_fresh_question(
                session,
                [
                    "Junto com esse cansaco, voce percebeu menos vontade de fazer as coisas?",
                    "Quando esse cansaco vem, ele pesa mais na sua energia ou na vontade de fazer as coisas?",
                    "Isso ficou mais com cara de cansaco fisico ou de desanimo para tocar o dia?",
                ],
            )
        if context["tristeza"] or context["interesse"]:
            return "Isso tem aparecido na maior parte dos dias ou varia bastante?"
        return default_next_question("mood", session.turn_count)

    return None


def build_contextual_support(
    session: LiaSessionState,
    user_message: str,
    stage: Literal["support", "anxiety", "mood", "closing"],
) -> str | None:
    context = build_lia_context(session, user_message)

    if stage == "closing":
        return None

    if context["unsure"]:
        return build_unsure_reply(session)

    if stage == "support":
        if context["wants_to_stop"]:
            return "Podemos encerrar sem problema."
        if context["no_issue"]:
            return "Pode deixar isso ser so um respiro por hoje."
        if context["positive"]:
            return "Se hoje estiver mais leve, tudo bem deixar isso ser so um respiro mesmo."
        if context["quick_pass"]:
            return "Tudo bem passar por aqui so pra dar um respiro."
        if context["mixed_feeling"]:
            return "Nao precisa definir o dia inteiro agora. A gente pode olhar so a parte que mais ficou com voce."
        if context["story_topic"]:
            return None
        if context["light_topic"]:
            return "Pode ir por onde ficar mais natural."
        if context["creative"]:
            return "Nao precisa transformar isso em problema. A gente pode partir dessa imagem mesmo."
        if session.turn_count == 1:
            if context["figurative_distress"]:
                return "Vamos separar uma parte disso, sem tentar resolver tudo agora."
            if context["sono"]:
                return "Dormir mal costuma deixar o resto do dia mais dificil de atravessar."
            if context["interesse"]:
                return "Ficar sem animo muda o jeito de encarar ate coisas simples."
            if context["study_test_context"] and context["concentracao"]:
                return "Isso pode deixar o estudo bem mais cansativo."
            return "Pode falar do jeito que vier."
        return None

    if stage == "anxiety":
        if session.turn_count == 1 and context["ansiedade"]:
            return None
        if context["pressure"] and context["work_study"]:
            return phrase_from_text(
                user_message,
                [
                    "Nao precisa desenrolar tudo de uma vez. Vamos so pegar a parte que mais apertou hoje.",
                    "Vamos ficar primeiro no pedaco que mais apertou.",
                    "A gente pode separar uma parte disso antes de tentar entender tudo.",
                    "A gente pode olhar para uma parte por vez, sem tentar resolver tudo nessa resposta.",
                    "Vamos deixar isso um pouco mais organizado, com calma.",
                ],
            )
        if context["pressure"] or context["worn_out"]:
            return first_fresh_phrase(
                session,
                [
                    "Pode me contar isso sem precisar deixar tudo bem explicado.",
                    "Nao precisa organizar tudo antes de falar.",
                    "Da para ir por uma parte menor agora.",
                ],
            )
        if context["palpitacao"]:
            return first_fresh_phrase(
                session,
                [
                    "Se quiser, me conta no seu ritmo. Nao precisa correr pra explicar.",
                    "Pode ficar so no que aconteceu no corpo agora.",
                    "A gente pode olhar primeiro para essa sensacao fisica.",
                ],
            )
        if context["ansiedade"] or context["controlar"] or context["relaxar"] or context["short_both"]:
            return first_fresh_phrase(
                session,
                [
                    "Se quiser, me conta no seu ritmo. Nao precisa correr pra explicar.",
                    "Pode falar so o pedaco que estiver mais claro agora.",
                    "A gente nao precisa fechar tudo nessa mensagem.",
                ],
            )
        if context["medo"]:
            return "Vamos so ficar no que esta acontecendo agora, sem tentar resolver tudo de uma vez."

    if stage == "mood":
        if context["interesse"] or contains_any(context["latest_text"], ["nao estou com vontade", "sem vontade", "nao tenho vontade"]):
            return first_fresh_phrase(
                session,
                [
                    "Tudo bem se hoje as coisas estiverem saindo em outro ritmo.",
                    "Nao precisa se cobrar para encaixar tudo no mesmo ritmo de sempre.",
                    "Pode ir me contando isso sem pressa.",
                ],
            )
        if context["sono"] or context["energia"] or context["stuck_without_improvement"] or context["worn_out"]:
            return first_fresh_phrase(
                session,
                [
                    "Pode ser muita coisa para organizar de uma vez.",
                    "A gente pode pegar so uma parte disso agora.",
                    "Nao precisa sair perfeito para fazer sentido aqui.",
                ],
            )
        if context["tristeza"]:
            return "A gente pode pegar isso por partes."

    if session.turn_count == 1:
        return "Pode ir por partes, do jeito que for mais facil."

    return None


def should_close_lia_session(
    session: LiaSessionState,
    analysis: LiaAnalysis,
    effective_stage: Literal["support", "anxiety", "mood", "closing"],
    enough_distress_data: bool,
) -> bool:
    if analysis.risk_level == "urgent":
        return True

    latest_user_message = normalize_optional_text(
        next((item.content for item in reversed(session.transcript) if item.role == "user"), None)
    ) or ""
    latest_context = build_lia_context(session, latest_user_message)

    if latest_context["quick_pass"] or latest_context["no_issue"]:
        return count_meaningful_user_messages(session) >= 2

    if latest_context["asks_for_options"] or latest_context["mentions_help"]:
        return False

    if latest_context["wants_to_stop"] and count_meaningful_user_messages(session) >= 3:
        return True

    if effective_stage not in {"anxiety", "mood", "closing"}:
        if session.current_topic == "closing" and count_meaningful_user_messages(session) >= 2:
            return True
        return False

    if not enough_distress_data:
        if session.current_topic == "closing" and count_meaningful_user_messages(session) >= 3:
            return True
        return False

    required_topics = ["main_focus", "distress_nature", "functional_impact", "frequency_duration"]
    if any(not session.topic_states[key].filled for key in required_topics):
        return False

    meaningful_messages = count_meaningful_user_messages(session)
    if meaningful_messages < 3 or session.turn_count < 4:
        return False

    if session.turn_count >= 8:
        return True

    if session.current_topic in {"concrete_example", "user_summary"} and recent_intent_count(session, session.current_topic) >= 2:
        return True

    if enough_distress_data and meaningful_messages >= 4 and session.current_topic in {"frequency_duration", "functional_impact"}:
        return True

    topics = derive_memory_topics(session)
    if not topics and sum(score or 0 for score in session.gad7_scores + session.phq9_scores) < 4:
        return False

    if session.current_topic == "closing":
        return True

    if analysis.ready_to_close and meaningful_messages >= 5 and session.turn_count >= 7:
        return True

    return bool(session.turn_count >= 8)


def ensure_lia_continuation(
    session: LiaSessionState,
    user_message: str,
    analysis: LiaAnalysis,
) -> LiaAnalysis:
    if analysis.risk_level == "urgent" or analysis.recommended_stage == "closing" or analysis.ready_to_close:
        return analysis

    has_question = bool(normalize_optional_text(analysis.next_question)) or "?" in (analysis.assistant_reply or "")
    has_support = bool(normalize_optional_text(analysis.assistant_reply))

    if has_question and has_support:
        return analysis

    fallback_question = build_contextual_question(session, user_message, analysis.recommended_stage)
    if not fallback_question:
        fallback_question = default_next_question(analysis.recommended_stage, session.turn_count)

    if not fallback_question:
        return analysis

    current_reply = normalize_optional_text(analysis.assistant_reply)
    if current_reply:
        if "?" in current_reply:
            return analysis
        analysis.assistant_reply = join_reply_parts(current_reply, None, fallback_question)
    else:
        analysis.assistant_reply = join_reply_parts(
            analysis.reflection,
            build_contextual_support(session, user_message, analysis.recommended_stage),
            fallback_question,
        )
    analysis.next_question = fallback_question
    return analysis


def sync_lia_stage(session: LiaSessionState, analysis: LiaAnalysis) -> None:
    session.current_topic = next_lia_topic(session)
    if session.current_topic == "closing":
        session.stage = "closing"
        return

    if session.current_topic in {"opening_state", "main_focus", "distress_context", "concrete_example", "user_summary"}:
        session.stage = "support"
    elif session.current_topic in {"distress_nature", "frequency_duration"}:
        session.stage = "anxiety"
    else:
        session.stage = "mood"

    analysis.recommended_stage = session.stage


def join_reply_parts(reflection: str, support: str | None = None, question: str | None = None) -> str:
    if not support and not question:
        return reflection.strip()

    clean_reflection = reflection.strip()
    clean_support = support.strip() if support else ""
    clean_question = question.strip() if question else ""

    parts = [part for part in [clean_reflection, clean_support, clean_question] if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts)


def normalize_score_list(raw_scores: list[Any], expected_length: int) -> list[int | None]:
    normalized_scores: list[int | None] = []
    for index in range(expected_length):
        value = raw_scores[index] if index < len(raw_scores) else None
        if value is None:
            normalized_scores.append(None)
            continue

        try:
            coerced = int(value)
        except (TypeError, ValueError):
            normalized_scores.append(None)
            continue

        normalized_scores.append(max(0, min(3, coerced)))

    return normalized_scores


def merge_scores(existing: list[int | None], incoming: list[int | None]) -> list[int | None]:
    merged: list[int | None] = []
    for index, current in enumerate(existing):
        next_value = incoming[index] if index < len(incoming) else None
        if next_value is None:
            merged.append(current)
            continue
        if current not in {None, 0} and next_value == 0:
            merged.append(current)
            continue
        merged.append(next_value)
    return merged


def default_stage_for_turn(turn_count: int) -> Literal["support", "anxiety", "mood", "closing"]:
    if turn_count <= 2:
        return "support"
    if turn_count <= 4:
        return "anxiety"
    if turn_count <= 7:
        return "mood"
    return "closing"


def default_next_question(stage: Literal["support", "anxiety", "mood", "closing"], turn_count: int) -> str | None:
    if stage == "support":
        if turn_count <= 1:
            return "Se quiser, me conta o que marcou seu dia ate aqui."
        return "Se quiser continuar, me fala qual parte disso mais ficou com voce."

    if stage == "anxiety":
        if turn_count <= 1:
            return "Isso esta mais forte so hoje ou ja vem pesando ha alguns dias?"
        return "Quando isso aparece, fica dificil relaxar ou controlar a preocupacao?"

    if stage == "mood":
        if turn_count <= 3:
            return "E nesses dias, como ficaram seu sono e sua energia?"
        return "Isso te deixou mais sem energia, mais para baixo ou os dois ao mesmo tempo?"

    return None


def build_grounded_lia_reply(session: LiaSessionState, user_message: str) -> str | None:
    context = build_lia_context(session, user_message)
    latest_text = context["latest_text"]

    if context["asks_about_professional"] or contains_any(
        latest_text,
        [
            "quero atendimento",
            "queria atendimento",
            "gostaria de atendimento",
            "seguir para atendimento",
            "seguir para triagem",
            "preciso conversar com alguem",
            "conversar com alguem",
            "motivo suficiente",
        ],
    ):
        return (
            "Acho um bom caminho. Conversar com um profissional pode te dar mais apoio para olhar para isso e pensar nos proximos passos. "
            "Quer que eu te encaminhe para a triagem agora?"
        )

    if contains_any(latest_text, ["culpa", "culpado", "culpada", "descontar nas pessoas", "desconto nas pessoas"]):
        return (
            "Essa culpa depois da irritacao pode deixar tudo mais pesado. "
            "O que costuma acontecer antes de voce acabar descontando nas pessoas?"
        )

    if contains_any(latest_text, ["nao consigo descansar", "nao consigo relaxar", "mesmo parado", "cabeca continua ligada", "mente continua ligada"]):
        return (
            "Isso de parar e a cabeca continuar ligada cansa bastante. "
            "Nessa hora, o que fica rodando mais: tarefas, cobrancas ou medo de esquecer algo?"
        )

    if contains_any(latest_text, ["afastando quem gosta", "afastar quem gosta", "afastar as pessoas", "afastando as pessoas"]):
        return (
            "Da para entender esse medo de acabar machucando ou afastando quem importa. "
            "Isso aparece mais quando voce esta irritado, cansado ou tentando se isolar?"
        )

    if context["decision_doubt"]:
        lead = first_fresh_phrase(
            session,
            [
                "Da para entender essa confusao.",
                "Da para comecar pelo que estiver mais facil de explicar.",
                "Nao precisa ter uma resposta pronta agora.",
            ],
        )
        question = first_fresh_question(
            session,
            [
                "O que te faz sentir que nao consegue decidir direito agora?",
                "Quando voce tenta pensar nisso, o que embaralha primeiro?",
                "Tem alguma situacao puxando essa sensacao de duvida, ou ela vem mais geral?",
            ],
        )
        return f"{lead} {capitalize_first(question)}"

    if context["financial_pressure"] and context["caregiving"]:
        question = first_fresh_question(
            session,
            [
                "o que esta apertando mais agora: as contas, o cuidado com seu filho ou a sensacao de estar sozinha?",
                "qual parte precisa de mais cuidado primeiro: dinheiro, rotina com seu filho ou falta de apoio?",
                "quando voce pensa nisso tudo, onde a pressao fica mais forte?",
            ],
        )
        return (
            "Tem responsabilidade, conta e cuidado com seu filho tudo junto ai. "
            f"Vamos separar isso em pedacos menores: {question}"
        )

    if context["work_offense"] and context["work_study"]:
        question = first_fresh_question(
            session,
            [
                "o que fica mais dificil depois dessas ofensas: continuar trabalhando, se defender ou nao levar aquilo para casa?",
                "essas ofensas vem de uma pessoa especifica ou do ambiente como um todo?",
                "quando isso acontece, o que fica mais forte em voce depois: tristeza, raiva ou medo de voltar para la?",
            ],
        )
        return (
            "Ofensa no trabalho pode ficar ecoando mesmo depois que o momento passa. "
            f"Me ajuda a entender melhor: {question}"
        )

    if context["social_withdrawal"]:
        question = first_fresh_question(
            session,
            [
                "esse afastamento vem mais por falta de energia, medo de incomodar ou vontade de sumir um pouco?",
                "quando voce se afasta, isso te da alivio ou acaba deixando tudo mais pesado depois?",
                "tem alguem de quem voce sente falta, mas nao tem conseguido se aproximar?",
            ],
        )
        return (
            "Quando a vontade e se afastar, da para olhar para isso com cuidado. "
            f"{question}"
        )

    if context["story_topic"]:
        question = first_fresh_question(
            session,
            [
                "do que e essa historia, pelo menos do jeito que ela aparece para voce agora? Pode ser conto, lembranca ou uma mistura dos dois.",
                "ela parece mais um conto inventado, uma lembranca sua ou uma mistura das duas coisas?",
                "qual parte dessa historia veio mais forte na sua cabeca?",
            ],
        )
        return (
            "Pode ser do seu jeito, por uma parte pequena mesmo. "
            f"{capitalize_first(question)}"
        )

    if context["study_test_context"] and (context["ansiedade"] or context["concentracao"] or context["pressure"]):
        question = first_fresh_question(
            session,
            [
                "quando voce tenta estudar, o que trava primeiro: a preocupacao, o foco ou o medo do resultado?",
                "isso aparece so nessa prova ou tambem em outras tarefas que exigem leitura e organizacao?",
                "a prova te assusta mais pelo conteudo, pelo tempo ou pela chance de dar errado?",
            ],
        )
        return (
            "Vamos organizar essa ansiedade com a prova. "
            f"{capitalize_first(question)} Isso aparece antes ou na hora da prova?"
        )

    if context["ansiedade"]:
        if "preocup" in context["latest_text"] and not contains_any(
            context["latest_text"], ["ansios", "nervos", "tenso", "panico"]
        ):
            question = first_fresh_question(
                session,
                [
                    "essa preocupacao aparece mais como pensamento repetindo, tensao no corpo ou dificuldade de desligar?",
                    "quando essa preocupacao vem, ela fica mais na cabeca ou muda algo no corpo tambem?",
                    "essa preocupacao esta ligada a alguma coisa especifica ou vem mais espalhada?",
                ],
            )
            return (
                "Vamos organizar essa preocupacao sem transformar tudo em uma coisa so. "
                f"{capitalize_first(question)}"
            )
        question = first_fresh_question(
            session,
            [
                "O que vem primeiro quando voce tenta falar disso?",
                "O que aconteceu hoje que trouxe isso mais para perto?",
                "Qual parte dessa ansiedade voce consegue explicar agora, mesmo que seja pouco?",
            ],
        )
        return f"Estou aqui com voce. {capitalize_first(question)}"

    if context["unwell"] or context["tristeza"] or context["interesse"] or context["energia"]:
        if context["energia"] and not (context["unwell"] or context["tristeza"] or context["interesse"]):
            question = first_fresh_question(
                session,
                [
                    "esse cansaco esta mais no corpo, na cabeca ou na vontade de fazer as coisas?",
                    "quando esse cansaco aparece, o que fica mais dificil de manter no dia?",
                    "esse cansaco veio mais de hoje ou ja vem acumulando?",
                ],
            )
            return (
                "Esse cansaco merece um pouco de espaco na conversa. "
                f"{question}"
            )
        if context["interesse"] and not context["unwell"]:
            question = first_fresh_question(
                session,
                [
                    "esse desanimo aparece mais como falta de vontade, tristeza ou cansaco acumulado?",
                    "quando o desanimo vem, o que voce mais deixa de fazer?",
                    "esse desanimo esta mais forte hoje ou ja vem de outros dias?",
                ],
            )
            return (
                "Esse desanimo nao precisa ser explicado inteiro agora. "
                f"{question}"
            )
        question = first_fresh_question(
            session,
            [
                "o que mais te pegou nisso hoje?",
                "o que mudou mais no seu dia: energia, vontade ou humor?",
                "isso esta te puxando mais para cansaco, tristeza ou desanimo?",
                "qual parte disso esta mais dificil de carregar agora?",
            ],
        )
        return (
            "Obrigado por colocar isso aqui. "
            f"{question}"
        )

    if context["pressure"] or context["worn_out"] or context["figurative_distress"]:
        if context["work_study"] and contains_any(
            latest_text,
            ["trabalho", "emprego", "empresa", "chefe", "servico", "serviço", "cobranca", "cobrança", "pressao", "pressão"],
        ):
            question = first_fresh_question(
                session,
                [
                    "no trabalho, qual parte dessa pressao esta mais dificil de ignorar agora?",
                    "essa pressao no trabalho vem mais de cobranca, volume de coisa ou medo de nao dar conta?",
                    "quando voce sai do trabalho, essa pressao continua com voce ou alivia um pouco?",
                ],
            )
            return (
                "Trabalho e casa juntos podem virar muita coisa para carregar no mesmo dia. "
                f"{capitalize_first(question)}"
            )
        if context["figurative_distress"]:
            question = first_fresh_question(
                session,
                [
                    "quando voce fala que a cabeca esta cheia, qual problema parece mais urgente agora?",
                    "essa sensacao na cabeca vem mais da quantidade de coisas ou de uma situacao especifica?",
                    "se a gente separar uma coisa primeiro, qual parte dessa cabeca cheia pede mais cuidado?",
                ],
            )
            return (
                "Essa imagem da cabeca cheia ajuda a mostrar que tem coisa demais disputando espaco ao mesmo tempo. "
                f"Vamos separar sem pressa: {question}"
            )
        question = first_fresh_question(
            session,
            [
                "qual parte dessa pressao esta mais impossivel de ignorar agora?",
                "isso pesa mais pela quantidade de coisas ou pela sensacao de nao ter espaco para respirar?",
                "se a gente separar uma coisa primeiro, qual parece mais urgente?",
            ],
        )
        return (
            "Parece que tem coisa demais disputando espaco ao mesmo tempo. "
            f"Vamos separar sem pressa: {question}"
        )

    return None


def reply_is_too_vague_for_context(session: LiaSessionState, user_message: str, reply: str) -> bool:
    context = build_lia_context(session, user_message)
    if not (
        context["decision_doubt"]
        or context["financial_pressure"]
        or context["caregiving"]
        or context["work_offense"]
        or context["social_withdrawal"]
        or context["story_topic"]
        or context["study_test_context"]
        or context["ansiedade"]
        or context["unwell"]
        or context["pressure"]
        or context["worn_out"]
    ):
        return False

    normalized_reply = normalize_for_match(reply)
    vague_fragments = [
        "o que mais ficou na sua cabeca hoje",
        "o que mais pesou hoje",
        "o que mais te pegou nesse dia",
        "qual e o principal pensamento ou sensacao",
        "como posso te ajudar",
        "o que voce quer colocar primeiro hoje",
        "o que esta mais dificil nisso agora",
        "me conta no seu ritmo",
    ]
    return any(fragment in normalized_reply for fragment in vague_fragments)


def count_positive_scores(scores: list[int | None]) -> int:
    return sum(1 for value in scores if (value or 0) > 0)


def count_meaningful_user_messages(session: LiaSessionState) -> int:
    return sum(
        1
        for item in session.transcript
        if item.role == "user" and is_probably_meaningful_message(item.content, allow_short_contextual=False)
    )


def infer_prompt_stage(session: LiaSessionState, user_message: str) -> Literal["support", "anxiety", "mood", "closing"]:
    context = build_lia_context(session, user_message)

    if context["positive"] or context["creative"]:
        return "support"

    if session.stage == "mood":
        return "mood"

    if session.turn_count >= 4 and (
        context["sono"]
        or context["energia"]
        or context["interesse"]
        or context["tristeza"]
        or context["stuck_without_improvement"]
        or count_answered_scores(session.gad7_scores) >= 2
    ):
        return "mood"

    if (
        context["ansiedade"]
        or context["pressure"]
        or context["palpitacao"]
        or context["controlar"]
        or context["relaxar"]
        or context["medo"]
        or user_needs_active_guidance(session, user_message)
    ):
        return "anxiety"

    if context["mixed_feeling"]:
        return "support"

    return "support" if session.stage == "opening" else session.stage


def infer_effective_stage(
    session: LiaSessionState,
    analysis: LiaAnalysis,
    user_message: str,
) -> Literal["support", "anxiety", "mood", "closing"]:
    context = build_lia_context(session, user_message)
    merged_gad_scores = merge_scores(session.gad7_scores, analysis.gad7_scores)
    merged_phq_scores = merge_scores(session.phq9_scores, analysis.phq9_scores)
    gad_answered = count_answered_scores(merged_gad_scores)
    phq_answered = count_answered_scores(merged_phq_scores)
    gad_positive = count_positive_scores(merged_gad_scores)
    phq_positive = count_positive_scores(merged_phq_scores)

    if analysis.risk_level == "urgent":
        return "closing"

    if context["positive"] or context["creative"]:
        return "support"

    if (
        context["tristeza"]
        or context["interesse"]
        or context["sono"]
        or context["energia"]
        or context["stuck_without_improvement"]
        or phq_positive >= 2
        or (phq_answered >= 3 and session.turn_count >= 3)
    ):
        return "mood"

    if (
        context["ansiedade"]
        or context["pressure"]
        or context["palpitacao"]
        or context["controlar"]
        or context["relaxar"]
        or context["medo"]
        or gad_positive >= 2
        or user_needs_active_guidance(session, user_message)
    ):
        return "anxiety"

    if analysis.recommended_stage in {"support", "anxiety", "mood", "closing"}:
        return analysis.recommended_stage

    return default_stage_for_turn(session.turn_count)


def scores_look_overfilled(
    session: LiaSessionState,
    analysis: LiaAnalysis,
    user_message: str,
) -> bool:
    context = build_lia_context(session, user_message)
    gad_answered = count_answered_scores(analysis.gad7_scores)
    phq_answered = count_answered_scores(analysis.phq9_scores)

    if session.turn_count <= 2 and (gad_answered > 3 or phq_answered > 3):
        return True

    if session.turn_count <= 3 and not (
        context["sono"] or context["energia"] or context["tristeza"] or context["interesse"] or context["stuck_without_improvement"]
    ) and phq_answered > 2:
        return True

    return False


def fill_missing_scores(primary: list[int | None], fallback: list[int | None]) -> list[int | None]:
    merged: list[int | None] = []
    for index, current in enumerate(primary):
        fallback_value = fallback[index] if index < len(fallback) else None
        merged.append(current if current is not None else fallback_value)
    return merged


def blend_signal_scores(primary: list[int | None], inferred: list[int | None]) -> list[int | None]:
    merged: list[int | None] = []
    for index, current in enumerate(primary):
        inferred_value = inferred[index] if index < len(inferred) else None
        if current is None:
            merged.append(inferred_value)
            continue
        if current == 0 and inferred_value not in {None, 0}:
            merged.append(inferred_value)
            continue
        merged.append(current)
    return merged


def infer_signal_scores(user_message: str) -> tuple[list[int | None], list[int | None], int | None]:
    text_value = normalize_for_match(user_message)
    gad7_scores: list[int | None] = [None] * 7
    phq9_scores: list[int | None] = [None] * 9

    if contains_any(text_value, ["ansios", "nervos", "tenso", "panico", "alerta"]):
        gad7_scores[0] = 1
    if contains_any(text_value, ["nao consigo parar", "nao desliga", "nao desliga", "nao para", "controlar"]):
        gad7_scores[1] = 1
    if contains_any(text_value, ["preocup", "pensando em tudo", "pensando demais"]):
        gad7_scores[2] = 1
    if contains_any(text_value, ["relax", "desligar", "demoro para desligar", "demoro para relaxar"]):
        gad7_scores[3] = 1
    if contains_any(text_value, ["agitado", "inquiet", "acelerado"]):
        gad7_scores[4] = 1
    if contains_any(text_value, ["irrit", "sem paciencia", "estress"]):
        gad7_scores[5] = 1
    if contains_any(text_value, ["algo ruim", "vai acontecer", "medo"]):
        gad7_scores[6] = 1

    if contains_any(text_value, ["sem vontade", "quase nada me anima", "automatico", "perderam a graca", "perdeu a graca"]):
        phq9_scores[0] = 1
    if contains_any(text_value, ["triste", "vazio", "apagada por dentro", "sem esperanca", "peso no humor"]):
        phq9_scores[1] = 1
    if contains_any(text_value, ["sono", "dorm", "deito", "acordo", "dormido mal"]):
        phq9_scores[2] = 1
    if contains_any(text_value, ["sem energia", "cansad", "cansaco", "exaust", "esgotad", "fadiga"]):
        phq9_scores[3] = 1
    if contains_any(text_value, ["apetite", "comer", "fome"]):
        phq9_scores[4] = 1
    if contains_any(text_value, ["culpa", "fracasso", "inutil"]):
        phq9_scores[5] = 1
    if contains_any(text_value, ["concentr", "foco", "nao consigo estudar"]):
        phq9_scores[6] = 1
    if contains_any(text_value, ["devagar", "travado", "agitado"]):
        phq9_scores[7] = 1
    if contains_any(text_value, ["nao penso em me machucar", "nao penso em morrer", "nao quero me machucar"]):
        phq9_scores[8] = 0
    elif contains_any(text_value, ["morrer", "sumir", "me machucar", "nao queria estar aqui"]):
        phq9_scores[8] = 1

    mood_value: int | None = None
    if contains_exact_phrase(text_value, ["estou bem", "to bem", "estou ok"]):
        mood_value = 5
    elif contains_any(text_value, ["nao estou bem", "nao me sinto bem", "triste", "vazio", "sem vontade", "sem energia", "esgotad"]):
        mood_value = 2
    elif contains_any(text_value, ["mais ou menos", "cansaco", "estresse"]):
        mood_value = 3

    return gad7_scores, phq9_scores, mood_value


def parse_json_object(raw_content: str) -> dict[str, Any]:
    cleaned = raw_content.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def build_lia_system_prompt(
    stage: Literal["opening", "support", "anxiety", "mood", "closing"],
    retry_hint: str | None = None,
) -> str:
    memory_context = ""
    if stage != "opening":
        memory_context = "Se houver memoria do usuario, use isso so como pano de fundo, sem soar invasivo."
    retry_context = f"\nCorrecao importante desta tentativa: {retry_hint}\n" if retry_hint else ""
    reference_context = build_lia_reference_prompt()
    return f"""
Voce e a propria Lia, uma assistente conversacional simples de apoio emocional em um app.
Responda em portugues do Brasil, com JSON puro e valido.
Use portugues natural, com acentos e cedilha quando fizer sentido.

Etapa atual da conversa: {stage}.
{memory_context}
{retry_context}
{reference_context}

Objetivo:
- acolher o usuario em tom humano;
- ser simpatica, presente e gentil, sem exagerar;
- agir como uma assistente conversacional simples com foco em apoio emocional;
- responder primeiro ao que o usuario trouxe, como um chat real, e so depois conduzir;
- escutar sem julgar, sem interpretar demais e sem transformar a fala do usuario em avaliacao;
- ajudar o usuario a encontrar o que ele quer dizer naquele momento;
- sugerir caminhos de conversa, nao decisoes de vida;
- oferecer uma frase simples de apoio antes da pergunta quando ajudar, sem soar poetico;
- fazer a conversa andar de forma leve: conecte a pergunta ao detalhe mais recente, mas sem soar como triagem;
- nao presumir sofrimento quando a fala for positiva, neutra, cotidiana ou simbolica;
- so aprofundar em ansiedade ou humor quando houver sinais disso ou quando o usuario pedir ajuda;
- nunca mencionar GAD-7, PHQ-9, diagnostico ou formulario;
- no maximo fazer uma pergunta curta por vez, e as vezes nao perguntar nada.

Mapeie sinais para estes itens:
GAD-7:
1 nervosismo ou tensao
2 dificuldade de controlar preocupacao
3 preocupacao excessiva
4 dificuldade para relaxar
5 inquietacao
6 irritabilidade
7 medo de que algo ruim aconteca

PHQ-9:
1 pouco interesse ou prazer
2 sentir-se para baixo ou sem esperanca
3 alteracoes de sono
4 cansaco ou pouca energia
5 alteracoes de apetite
6 culpa, fracasso ou baixa autoestima
7 dificuldade de concentracao
8 lentidao ou agitacao
9 pensamentos de morte ou autoagressao

Retorne EXATAMENTE estas chaves:
assistant_reply: a mensagem principal que o usuario vai ler, natural, acolhedora e sem soar roteirizada
reflection: string curta de apoio interno, no maximo 2 frases
next_question: pergunta curta para apoio interno, ou null se a conversa puder seguir sem pergunta
risk_level: "none", "attention" ou "urgent"
mood_value: inteiro de 1 a 5, ou null
gad7_scores: lista com 7 valores entre 0 e 3, ou null quando nao houver base
phq9_scores: lista com 9 valores entre 0 e 3, ou null quando nao houver base
ready_to_close: boolean
recommended_stage: "support", "anxiety", "mood" ou "closing"

Regras:
- use 0 quando o usuario disser claramente que algo nao acontece;
- use null quando a conversa ainda nao der base suficiente;
- se houver mencao de morte, suicidio, autoagressao ou risco imediato, use risk_level "urgent";
- se a ultima mensagem estiver sem sentido claro ou parecer apenas ruido, diga que nao entendeu, peca reformulacao simples, mantenha scores como null e ready_to_close false;
- se a fala for positiva, neutra, cotidiana ou simbolica, use recommended_stage "support";
- se a fala for positiva, como "hoje estou bem" ou "so passei por aqui", nao use "sinto muito" nem trate isso como sofrimento;
- se o usuario disser que esta bem e quiser so passar rapidinho, valide isso com leveza e deixe a porta aberta, sem investigar sintomas;
- se a fala for simbolica, como chuva, silencio, flores ou mar, responda com curiosidade gentil e sem assumir dor;
- se a fala for simbolica, fale da imagem ou do significado dela; nao reescreva isso como sofrimento escondido;
- se o usuario disser que esta ansioso, acolha e deixe ele escolher por onde comecar; nao transforme isso em interrogatorio;
- nao diga que o usuario "tem ansiedade ultimamente" se ele so mencionou estar ansioso agora;
- se a fala for apenas "estou ansioso" ou parecida, responda com linguagem livre e natural, sem frase fixa, e convide o usuario a contar o que vier primeiro;
- nao transforme uma duvida, historia, lembranca ou assunto criativo em sintoma antes de entender o que aquilo significa para o usuario;
- nao diga que algo "deve ser estressante", "parece estar incomodando" ou "esta pesando" se o usuario ainda nao indicou sofrimento nesse ponto;
- evite comecar com interpretacoes como "isso parece", "essa duvida parece", "essa ansiedade parece", "isso soa como";
- prefira falas ativas de apoio na conversa, como "vamos organizar isso", "a gente separa em pedacos menores", "me conta o que veio primeiro";
- nao repita "posso te ajudar" em respostas seguidas; a Lia ja esta ali para ajudar;
- evite frases com tom terapeutico de sessao, como "vamos ficar nesse momento", "ficar com essa ansiedade", "olhar para isso com cuidado";
- se o usuario trouxer uma historia, ideia ou lembranca, pergunte primeiro do que se trata, qual parte veio mais forte ou por onde ele quer comecar;
- nao fale em foco, concentracao, estudo ou atencao se o usuario nao trouxe isso claramente;
- evite aberturas artificiais como "entendo melhor agora"; responda como uma conversa normal;
- nao explique suas regras internas para o usuario;
- nao diga frases como "sem colocar rotulo", "nao vou te diagnosticar", "vamos pegar uma parte sem resolver tudo" ou "sem precisar chegar com tudo resolvido";
- transforme esse cuidado em linguagem natural, por exemplo: fale do que apareceu e faca uma pergunta simples;
- se o contexto envolver prova, estudo, leitura, foco ou organizacao, investigue de forma leve se a dificuldade aparece em outros momentos, sem sugerir diagnosticos como TDAH, dislexia ou TPAC;
- quando o usuario pedir ajuda ou disser que nao sabe o que fazer, ofereca caminhos simples: organizar o que sente, pensar em um proximo passo ou seguir para triagem;
- se o usuario pedir conselho dizendo "o que devo fazer", nao decida por ele; ajude a organizar possibilidades e pergunte o que faria sentido para ele;
- voce pode sugerir caminhos de conversa, mas varie a forma e evite repetir a mesma estrutura de duas opcoes;
- bons apoios soam cotidianos, como "da para comecar pelo que estiver mais facil de explicar" ou "nao precisa ter uma resposta pronta agora";
- evite frases bonitas demais ou poeticas; a Lia deve soar como uma pessoa falando normalmente;
- use listas de possibilidades com cuidado; nao transforme toda pergunta em alternativas;
- maus exemplos sao ordens ou conselhos de vida, como "voce deve terminar", "voce precisa confrontar", "faca tal coisa";
- nao sugira decisoes externas como terminar relacionamento, pedir demissao, confrontar alguem ou mudar rotina sem o usuario construir isso;
- quando o usuario perguntar sobre profissional, consulta, triagem ou se alguem pode ajudar, responda a pergunta de forma clara antes de voltar ao roteiro;
- se o usuario trouxer escolhas, duvidas ou decisao, nao julgue a escolha; convide ele a contar o que esta em jogo ou qual parte ele consegue dizer agora;
- se o usuario trouxer contas, filho, trabalho, ofensas, estudo ou isolamento, use esse detalhe com naturalidade, sem transformar em checklist;
- se o sofrimento vier de outros dias ou semanas e impactar sono, rotina, trabalho ou estudo, convide com cuidado para triagem com profissional;
- se o usuario disser que nao esta bem, pedir ajuda, falar de cansaco, pressao, vazio, pouca vontade, sono ruim ou pouca energia, nao responda de forma passiva;
- nesses casos, assistant_reply deve trazer presenca, uma abertura para o usuario falar e, quando fizer sentido, uma pergunta curta;
- o apoio vem antes de qualquer orientacao; nao pule direto para dica, tarefa ou solucao;
- nao use respostas vagas como "estou aqui para ouvir" ou "como posso te ajudar" sem tomar iniciativa;
- evite perguntas vagas quando ja existe contexto, como "o que mais ficou na sua cabeca hoje?", "o que mais pesou hoje?" ou "o que te pegou?";
- essas perguntas so servem quando o usuario ainda nao trouxe quase nada;
- se o usuario disser "nao estou me sentindo muito bem", uma boa direcao seria algo como: "Hoje parece que nao esta simples para voce. Pode me contar do jeito que vier: o que mais te pegou nisso?";
- se o usuario pedir ajuda, uma boa direcao seria algo como: "Tudo bem. Me fala qual parte disso esta mais dificil de carregar agora.";
- nao minimize com frases como "e natural sentir-se assim de vez em quando" ou "todo mundo passa por isso";
- evite tom de coach, autoajuda ou produtividade;
- nao use frases como "vou sugerir", "vou dar um conselho", "pense em uma tarefa", "tome um cafe", "tome um cha", "faca uma caminhada", "veja um video engracado";
- nao elogie nem celebre de forma exagerada; prefira calma, presenca e delicadeza;
- simpatia aqui significa calor humano simples: "estou aqui", "obrigada por me contar", "a gente pode ir com calma", "isso ja ajuda a comecar";
- use pequenas frases simpaticas quando combinarem com a fala, mas nao transforme toda resposta em acolhimento repetido;
- nao faca perguntas de coaching futuro, como "o que voce pode fazer amanha?" ou "qual atividade te faria bem?". Prefira perguntas simples, concretas e humanas;
- evite duas perguntas na mesma resposta;
- evite perguntas amplas como "o que e mais importante hoje?" ou "o que voce faz para relaxar?" quando a conversa ainda precisa mapear sintomas;
- evite frases que julgam a capacidade do usuario, como "ate falar disso ja pode parecer muito";
- nas fases iniciais, nao pareca estar preenchendo uma ficha; deixe o usuario escolher por onde comecar;
- use null com generosidade nos scores. So marque 0 quando houver negacao explicita. Nao preencha itens nao mencionados;
- nas primeiras 2 ou 3 mensagens, nao preencha muitos itens de uma vez. Avance aos poucos;
- se o usuario negar autoagressao, nao trate isso como urgencia;
- extraia sinais de ansiedade, humor, sono, energia, interesse e preocupacao por tras da conversa, sem listar esses temas para o usuario;
- se precisar perguntar, faca isso como conversa natural, nao como triagem;
- cite pelo menos um detalhe concreto da fala mais recente do usuario ou do contexto imediatamente anterior;
- evite frases genericas repetidas como "obrigada por me contar isso";
- nao comece toda resposta com "entendi";
- tambem evite trocar "entendi" por sinonimos mecanicos em toda resposta; varie de verdade;
- varie o tom de abertura entre acolhimento, observacao gentil, validacao ou curiosidade;
- se o usuario responder algo curto como "sim" ou "nao", use a pergunta anterior e o contexto recente para formular a resposta;
- quando fizer sentido, inclua no maximo uma orientacao pratica bem curta, mas so depois de acolher de verdade;
- frases como "vamos por partes", "nao precisa explicar tudo de uma vez", "nao precisa carregar isso sozinho", "eu fico com voce nessa parte" sao melhores do que conselhos prontos;
- use essas frases com moderacao; nao repita o mesmo acolhimento em respostas seguidas;
- se o usuario disser algo como "estou bem", valide isso e nao trate como problema;
- se o usuario disser algo como "mais ou menos", trate isso como ambivalencia, nao como sofrimento grave;
- se o usuario corrigir a propria fala, aceite a correcao e siga a partir dela;
- se o usuario nao quiser continuar, respeite isso com leveza, sem pressionar;
- se o usuario falar algo simbolico, como pensar em flores, musica, chuva ou mar, responda com curiosidade gentil e sem presumir dor;
- a pergunta seguinte deve soar como conversa real, nao como formulario;
- assistant_reply deve soar como uma unica mensagem de chat, nao como dois blocos tecnicos;
- prefira 1 ou 2 frases naturais; use 3 apenas quando realmente ajudar;
- assistant_reply e o campo mais importante; reflection e next_question sao apoio interno;
- se ready_to_close for true, assistant_reply deve oferecer uma transicao cuidadosa, sem cortar a liberdade do usuario de continuar;
- se stage for closing, nao abra nova investigacao longa; acolha, indique a triagem quando fizer sentido e deixe claro que o usuario pode seguir pelo botao ou voltar depois;
- se a mensagem for confusa ou pouco clara, assistant_reply deve pedir esclarecimento de forma humana, sem usar resposta pronta robotica;
- se houver memoria acumulada, retome isso com delicadeza e so quando ajudar a conversa atual;
- quando os sinais recentes ja tiverem passado por ansiedade/corpo e depois por sono, energia, interesse ou humor, prefira oferecer triagem ou uma pausa em vez de continuar coletando;
- so use ready_to_close true quando houver varias trocas ou pedido claro de triagem; nao finalize cedo so porque ja deu para preencher dados.
""".strip()


def build_lia_memory_prompt(session: LiaSessionState) -> str:
    return "Memoria atual do usuario: " + (
        (
            f"resumo acumulado: {session.memory.summary}. "
            if session.memory.summary
            else "sem resumo acumulado. "
        )
        + (
            f"ultimo contexto: {session.memory.recent_summary}. "
            if session.memory.recent_summary
            else ""
        )
        + (
            "topicos recorrentes: " + ", ".join(session.memory.topics) + "."
            if session.memory.topics
            else ""
        )
    )


def call_ollama_for_lia(
    session: LiaSessionState,
    retry_hint: str | None = None,
    forced_stage: Literal["support", "anxiety", "mood", "closing"] | None = None,
) -> LiaAnalysis:
    if not OLLAMA_ENABLED:
        raise RuntimeError("Ollama disabled")

    latest_user_message = next((item.content for item in reversed(session.transcript) if item.role == "user"), "")
    prompt_stage = forced_stage or (infer_prompt_stage(session, latest_user_message) if latest_user_message else session.stage)

    payload = {
        "model": resolve_ollama_model(),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.6, "num_predict": 420},
        "messages": [
            {"role": "system", "content": build_lia_system_prompt(prompt_stage, retry_hint)},
            {"role": "system", "content": build_lia_memory_prompt(session)},
            *[{"role": item.role, "content": item.content} for item in session.transcript],
        ],
    }

    request = urllib_request.Request(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        raw_payload = json.loads(response.read().decode("utf-8"))

    content = raw_payload.get("message", {}).get("content", "")
    parsed = parse_json_object(content)
    assistant_reply = normalize_optional_text(parsed.get("assistant_reply"))
    reflection = str(parsed.get("reflection") or assistant_reply or "Estou aqui com voce.")
    next_question = parsed.get("next_question")

    if not assistant_reply:
        raise ValueError("Ollama returned no assistant reply")

    return LiaAnalysis(
        assistant_reply=str(assistant_reply),
        reflection=reflection,
        next_question=next_question,
        risk_level=parsed.get("risk_level") or "none",
        mood_value=parsed.get("mood_value"),
        gad7_scores=normalize_score_list(parsed.get("gad7_scores") or [], 7),
        phq9_scores=normalize_score_list(parsed.get("phq9_scores") or [], 9),
        ready_to_close=bool(parsed.get("ready_to_close")),
        recommended_stage=parsed.get("recommended_stage") or default_stage_for_turn(session.turn_count),
    )


def parse_lia_analysis_from_content(content: str) -> LiaAnalysis:
    parsed = parse_json_object(content)
    assistant_reply = normalize_optional_text(parsed.get("assistant_reply"))
    reflection = str(parsed.get("reflection") or assistant_reply or "Estou aqui com voce.")
    next_question = parsed.get("next_question")

    if not assistant_reply:
        raise ValueError("LLM returned no assistant reply")

    return LiaAnalysis(
        assistant_reply=str(assistant_reply),
        reflection=reflection,
        next_question=next_question,
        risk_level=parsed.get("risk_level") or "none",
        mood_value=parsed.get("mood_value"),
        gad7_scores=normalize_score_list(parsed.get("gad7_scores") or [], 7),
        phq9_scores=normalize_score_list(parsed.get("phq9_scores") or [], 9),
        ready_to_close=bool(parsed.get("ready_to_close")),
        recommended_stage=parsed.get("recommended_stage") or default_stage_for_turn(0),
    )


def call_openrouter_for_lia(
    session: LiaSessionState,
    retry_hint: str | None = None,
    forced_stage: Literal["support", "anxiety", "mood", "closing"] | None = None,
) -> LiaAnalysis:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter disabled")

    latest_user_message = next((item.content for item in reversed(session.transcript) if item.role == "user"), "")
    prompt_stage = forced_stage or (infer_prompt_stage(session, latest_user_message) if latest_user_message else session.stage)

    payload = {
        "model": OPENROUTER_MODEL,
        "temperature": 0.6,
        "max_tokens": 420,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": build_lia_system_prompt(prompt_stage, retry_hint)},
            {"role": "system", "content": build_lia_memory_prompt(session)},
            *[{"role": item.role, "content": item.content} for item in session.transcript],
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "X-Title": OPENROUTER_APP_NAME,
    }
    if OPENROUTER_SITE_URL:
        headers["HTTP-Referer"] = OPENROUTER_SITE_URL

    request = urllib_request.Request(
        OPENROUTER_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    with urllib_request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        raw_payload = json.loads(response.read().decode("utf-8"))

    content = raw_payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    return parse_lia_analysis_from_content(content)


def call_cloud_or_local_lia(
    session: LiaSessionState,
    retry_hint: str | None = None,
    forced_stage: Literal["support", "anxiety", "mood", "closing"] | None = None,
) -> LiaAnalysis:
    if OPENROUTER_API_KEY:
        return call_openrouter_for_lia(session, retry_hint=retry_hint, forced_stage=forced_stage)
    return call_ollama_for_lia(session, retry_hint=retry_hint, forced_stage=forced_stage)


def infer_risk_level_from_message(user_message: str) -> Literal["none", "attention", "urgent"]:
    text_value = normalize_for_match(user_message)
    if contains_any(text_value, ["me matar", "suicid", "me machucar", "nao quero viver", "nao queria estar aqui"]):
        return "urgent"
    if contains_any(text_value, ["sumir", "desaparecer", "nao queria lidar com nada"]):
        return "attention"
    return "none"


def generate_lia_plain_reply(
    session: LiaSessionState,
    user_message: str,
    stage: Literal["support", "anxiety", "mood", "closing"],
    retry_hint: str | None = None,
    repair_reason: str | None = None,
) -> str | None:
    if not OLLAMA_ENABLED:
        return None

    context = build_lia_context(session, user_message)
    question_rule = "Use no maximo uma pergunta curta." if not context["quick_pass"] else (
        "Nao faca pergunta investigativa. Valide a leveza e deixe a porta aberta com delicadeza."
    )
    extra_style_hint = ""
    if context["quick_pass"]:
        extra_style_hint = (
            "O usuario so quis passar rapido. Valide isso com leveza, sem transformar em problema e sem investigar sintomas."
        )
    elif context["positive"]:
        extra_style_hint = (
            "O usuario esta bem ou neutro. Nao dramatize, nao investigue sintomas sem motivo e nao use 'sinto muito'."
        )
    elif context["creative"]:
        extra_style_hint = (
            "O usuario falou de forma simbolica. Responda com curiosidade suave sobre a imagem, sem presumir sofrimento."
        )
    elif user_needs_active_guidance(session, user_message):
        extra_style_hint = (
            "O usuario nao esta bem e precisa de iniciativa. Primeiro reconheca a experiencia concreta dele, "
            "depois ofereca presenca curta, e so entao faca uma pergunta simples e humana sobre o que mais pesou hoje. "
            "Evite conselhos prontos, tom de psicologo e perguntas como 'mente ou corpo'."
        )
    elif stage == "closing":
        extra_style_hint = "A conversa ja reuniu contexto suficiente. Feche com sintese curta e um proximo passo simples."

    system_prompt = (
        "Voce e Lia, uma assistente de apoio emocional. "
        "Responda apenas com a mensagem final, sem JSON e sem explicacoes extras. "
        "Use portugues do Brasil simples, tom humano e acolhedor, em ate 80 palavras. "
        "Acolha primeiro; depois, se fizer sentido, traga uma orientacao minima. "
        "Nao mencione diagnostico, questionario, pontuacao ou avaliacao. "
        "Nao use a palavra 'doente' para reformular cansaco, tristeza, ansiedade ou inseguranca. "
        "Nao pergunte se o usuario tem uma pergunta para voce. "
        "Nao fale de experiencias, cansaco, memoria ou sentimentos proprios como 'eu tambem' ou 'ultimamente eu'. "
        "Nao cite foco, concentracao, estudo ou atencao se o usuario nao trouxe isso claramente. "
        "Evite aberturas artificiais como 'entendo melhor agora'. "
        f"Etapa: {stage}. {question_rule} {extra_style_hint} "
    )
    if repair_reason:
        system_prompt += f"Motivo do reparo: {repair_reason}. "
    if retry_hint:
        system_prompt += f"Ajuste adicional: {retry_hint}"
    reference_context = build_lia_reference_prompt()
    if reference_context:
        system_prompt += f" {reference_context}"

    payload = {
        "model": resolve_ollama_model(),
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 140, "num_ctx": 2048},
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "system", "content": build_lia_memory_prompt(session)},
            *[{"role": item.role, "content": item.content} for item in session.transcript],
        ],
    }

    request = urllib_request.Request(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        raw_payload = json.loads(response.read().decode("utf-8"))

    return clean_lia_model_text(raw_payload.get("message", {}).get("content"))


def build_lia_rewrite_seed(
    session: LiaSessionState,
    user_message: str,
    analysis: LiaAnalysis,
) -> str:
    context = build_lia_context(session, user_message)
    allowed_question = normalize_optional_text(analysis.next_question)
    support = build_contextual_support(session, user_message, analysis.recommended_stage)
    reflection = normalize_optional_text(analysis.reflection) or ""

    intent_parts = [
        f"etapa: {analysis.recommended_stage}",
        f"abertura base: {reflection}" if reflection else None,
        f"apoio base: {support}" if support else None,
        f"pergunta permitida: {allowed_question}" if allowed_question else "sem pergunta obrigatoria",
    ]

    if context["light_topic"]:
        intent_parts.append("tema leve: manter a conversa leve e direta, sem dramatizar")
    if context["quick_pass"] or context["no_issue"]:
        intent_parts.append("check-in breve: nao investigar sintomas")
    if user_needs_active_guidance(session, user_message):
        intent_parts.append("o usuario precisa de acolhimento concreto e continuidade")
    if context["ansiedade"] and not (context["duration"] or context["latest_duration"]):
        intent_parts.append(
            "ansiedade: falar de forma livre, sem diagnosticar, sem dizer que e frequente, e confirmar como aparece"
        )

    return " | ".join(part for part in intent_parts if part)


def rewrite_lia_from_analysis(
    session: LiaSessionState,
    user_message: str,
    analysis: LiaAnalysis,
    retry_hint: str | None = None,
) -> str | None:
    if not OLLAMA_ENABLED:
        return None

    context = build_lia_context(session, user_message)
    base_reply = normalize_optional_text(analysis.assistant_reply) or normalize_optional_text(analysis.reflection)
    if not base_reply:
        return None

    question_rule = (
        "Sem pergunta investigativa. Se fizer sentido, deixe uma porta aberta leve."
        if context["quick_pass"] or context["no_issue"]
        else "Use no maximo uma pergunta curta, e somente se ela ja estiver permitida no roteiro."
    )

    system_prompt = (
        "Voce vai apenas redigir melhor a resposta da Lia. "
        "Nao mude o sentido, nao mude o foco e nao invente um novo rumo para a conversa. "
        "Use portugues do Brasil simples, humano, natural e acolhedor. "
        "Use portugues natural, com acentos quando fizer sentido. Nao use JSON. Nao use cabecalhos. "
        "Nao fale de si mesma. Nao use 'eu tambem'. "
        "Nao use a palavra 'doente'. "
        "Nao pergunte se o usuario tem uma pergunta para voce. "
        "Nao recuse conversa neutra ou leve. "
        "Nao cite emergencia, crise, suicidio ou ajuda profissional se o roteiro nao trouxer isso. "
        "Nao use texto meta como 'ultima mensagem do usuario', 'resposta anterior da Lia' ou 'reescreva agora'. "
        "Seu trabalho e apenas pegar a intencao ja definida e dizer isso de um jeito mais vivo. "
        "Nao copie frases base como se fossem obrigatorias; preserve o roteiro, mas escreva com linguagem livre e natural. "
        f"{question_rule} "
        f"Roteiro obrigatorio deste turno: {build_lia_rewrite_seed(session, user_message, analysis)}."
    )
    reference_context = build_lia_reference_prompt()
    if reference_context:
        system_prompt += f" {reference_context}"
    if retry_hint:
        system_prompt += f" Ajuste extra: {retry_hint}"

    payload = {
        "model": resolve_ollama_model(),
        "stream": False,
        "options": {"temperature": 0.55, "num_predict": 120, "num_ctx": 2048},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Mensagem do usuario: {user_message}\n"
                    f"Resposta base da Lia: {base_reply}\n"
                    "Escreva apenas a resposta final da Lia."
                ),
            },
        ],
    }

    request = urllib_request.Request(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        raw_payload = json.loads(response.read().decode("utf-8"))

    return clean_lia_model_text(raw_payload.get("message", {}).get("content"))


def build_ai_rescue_analysis(
    session: LiaSessionState,
    user_message: str,
    retry_hint: str | None = None,
    repair_reason: str | None = None,
) -> LiaAnalysis:
    stage = infer_prompt_stage(session, user_message)
    assistant_reply = generate_lia_plain_reply(
        session,
        user_message,
        stage=stage,
        retry_hint=retry_hint,
        repair_reason=repair_reason,
    )
    if not assistant_reply:
        raise ValueError("Ollama returned no plain assistant reply")

    inferred_gad_scores, inferred_phq_scores, inferred_mood_value = infer_signal_scores(user_message)
    risk_level = infer_risk_level_from_message(user_message)
    recommended_stage = infer_recommended_stage(session, user_message, risk_level)

    return LiaAnalysis(
        assistant_reply=assistant_reply,
        reflection=assistant_reply,
        next_question=None,
        risk_level=risk_level,
        mood_value=inferred_mood_value,
        gad7_scores=inferred_gad_scores,
        phq9_scores=inferred_phq_scores,
        ready_to_close=stage == "closing",
        recommended_stage=recommended_stage,
    )


def rewrite_lia_reply(
    session: LiaSessionState,
    user_message: str,
    original_reply: str,
    stage: Literal["support", "anxiety", "mood", "closing"],
) -> str | None:
    if not OLLAMA_ENABLED:
        return None

    context = build_lia_context(session, user_message)
    extra_style_hint = ""
    if context["quick_pass"]:
        extra_style_hint = (
            "O usuario so quis passar rapidinho. Valide isso e deixe a porta aberta. Nao investigue sintomas."
        )
    elif context["positive"]:
        extra_style_hint = (
            "O usuario esta bem ou neutro. Valide a leveza, nao use 'sinto muito' e nao force sofrimento. "
            "Ofereca espaco sem pressao."
        )
    elif context["creative"]:
        extra_style_hint = (
            "O usuario falou de forma simbolica. Responda com curiosidade gentil sobre a imagem, sem assumir dor nem dramatizar."
        )
    elif user_needs_active_guidance(session, user_message):
        extra_style_hint = (
            "O usuario precisa de conducao ativa. Mantenha acolhimento breve, uma sugestao pequena para agora e uma pergunta observacional."
        )

    question_limit = (
        "Se o usuario so quiser passar rapido, nao faca pergunta investigativa. "
        if context["quick_pass"]
        else "Use no maximo uma pergunta. "
    )
    rewrite_system_prompt = (
        "Voce vai reescrever a resposta da Lia em portugues do Brasil natural, com acentos quando fizer sentido. "
        "Mantenha um tom humano e acolhedor. "
        "A nova resposta deve conter reconhecimento concreto do que a pessoa trouxe, uma frase curta de apoio ou presenca, "
        "e uma pergunta curta, observacional e clinica disfarcada de conversa. "
        "Nao use frases passivas como 'estou aqui para ouvir'. "
        "Nao use frases minimizantes como 'e natural sentir-se assim de vez em quando'. "
        "Nao use tom de coach, autoajuda ou produtividade. "
        "Nao use a palavra 'doente' para descrever o estado do usuario. "
        "Nao pergunte se o usuario tem uma pergunta para voce. "
        "Nao fale de experiencias, cansaco, memoria ou sentimentos proprios como 'eu tambem' ou 'ultimamente eu'. "
        "Nao pule direto para dica ou solucao antes de acolher. "
        "Nao faca perguntas de coaching futuro como 'o que voce pode fazer amanha'. "
        f"{question_limit}"
        f"A etapa atual e {stage}. "
        f"{extra_style_hint}"
    )
    reference_context = build_lia_reference_prompt()
    if reference_context:
        rewrite_system_prompt += f" {reference_context}"

    payload = {
        "model": resolve_ollama_model(),
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 220},
        "messages": [
            {
                "role": "system",
                "content": rewrite_system_prompt,
            },
            {
                "role": "user",
                "content": (
                    f"Ultima mensagem do usuario: {user_message}\n"
                    f"Resposta anterior da Lia: {original_reply}\n"
                    "Reescreva agora a melhor resposta final da Lia."
                ),
            },
        ],
    }

    request = urllib_request.Request(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
        raw_payload = json.loads(response.read().decode("utf-8"))

    return clean_lia_model_text(raw_payload.get("message", {}).get("content"))


def clean_lia_model_text(raw_text: str | None) -> str | None:
    cleaned = normalize_optional_text(raw_text)
    if not cleaned:
        return None

    cleaned = re.sub(r"<\|[^|]+?\|>", " ", cleaned)
    cleaned = re.sub(r"^aqui vai lia:\s*", "", cleaned.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"^ola lia!?\s*", "", cleaned.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \"'")

    if cleaned.startswith("- "):
        cleaned = cleaned.replace("- ", "", 1).strip()

    return normalize_optional_text(cleaned)


def repair_lia_reply(
    session: LiaSessionState,
    user_message: str,
    original_reply: str,
    stage: Literal["support", "anxiety", "mood", "closing"],
    retry_hint: str,
) -> str | None:
    rewritten_reply = rewrite_lia_reply(session, user_message, original_reply, stage)
    if rewritten_reply:
        return rewritten_reply

    return generate_lia_plain_reply(
        session,
        user_message,
        stage=stage,
        retry_hint=retry_hint,
        repair_reason=f"Resposta anterior ruim: {original_reply}",
    )


def should_require_strict_support_context(session: LiaSessionState, user_message: str) -> bool:
    context = build_lia_context(session, user_message)
    return bool(context["positive"] or context["quick_pass"] or context["creative"])


def fallback_lia_analysis(session: LiaSessionState, user_message: str) -> LiaAnalysis:
    context = build_lia_context(session, user_message)
    text_value = context["combined_text"]
    gad7_scores: list[int | None] = [None] * 7
    phq9_scores: list[int | None] = [None] * 9

    recent_assistant = normalize_for_match(latest_assistant_message(session) or "")
    if session.pause_used and (
        "voce tinha escolhido" in recent_assistant or "assunto leve" in recent_assistant
    ):
        reflection = build_post_pause_reply(session, user_message)
        return LiaAnalysis(
            assistant_reply=reflection,
            reflection=reflection,
            next_question=None,
            risk_level="none",
            mood_value=session.mood_value,
            gad7_scores=gad7_scores,
            phq9_scores=phq9_scores,
            ready_to_close=False,
            recommended_stage="support",
        )

    risk_level: Literal["none", "attention", "urgent"] = "none"
    if contains_risk_phrase(text_value, ["me matar", "suicid", "sumir", "nao quero viver", "me machucar"]):
        risk_level = "urgent"

    if any(term in text_value for term in ["ansios", "nervos", "tenso", "panico", "preocup"]):
        gad7_scores[0] = 2
    if any(term in text_value for term in ["controlar", "nao consigo parar", "nao desligo", "nao para"]):
        gad7_scores[1] = 2
    if any(term in text_value for term in ["preocup", "pensando demais", "cabeça cheia", "cabeca cheia"]):
        gad7_scores[2] = 2
    if any(term in text_value for term in ["relax", "descans", "respirar"]):
        gad7_scores[3] = 2
    if any(term in text_value for term in ["agitado", "inquiet", "acelerado"]):
        gad7_scores[4] = 2
    if any(term in text_value for term in ["irrit", "raiva", "estress"]):
        gad7_scores[5] = 2
    if any(term in text_value for term in ["medo", "algo ruim", "vai dar errado"]):
        gad7_scores[6] = 2

    if any(term in text_value for term in ["sem vontade", "desanim", "nao tenho prazer", "nao sinto vontade"]):
        phq9_scores[0] = 2
    if any(term in text_value for term in ["triste", "pra baixo", "sem esperanca", "vazio"]):
        phq9_scores[1] = 2
    if any(term in text_value for term in ["sono", "dormir", "inson", "acordo"]):
        phq9_scores[2] = 2
    if any(term in text_value for term in ["cansad", "sem energia", "exaust"]):
        phq9_scores[3] = 2
    if any(term in text_value for term in ["apetite", "comer", "fome"]):
        phq9_scores[4] = 1
    if any(term in text_value for term in ["culpa", "fracasso", "inutil", "peso para os outros"]):
        phq9_scores[5] = 2
    if any(term in text_value for term in ["concentr", "foco", "nao consigo estudar"]):
        phq9_scores[6] = 2
    if any(term in text_value for term in ["devagar", "travado", "agitado"]):
        phq9_scores[7] = 1
    if contains_risk_phrase(text_value, ["morrer", "sumir", "nao queria estar aqui", "me machucar"]):
        phq9_scores[8] = 2
        risk_level = "urgent"

    mood_value = 3
    if context["positive"]:
        mood_value = 4
    if any(term in text_value for term in ["triste", "exaust", "ansios", "pra baixo", "sobrecarreg"]):
        mood_value = 2
    if any(term in text_value for term in ["muito bem", "mais leve", "melhor", "tranquilo"]):
        mood_value = 4

    recommended_stage = infer_recommended_stage(session, user_message, risk_level)
    next_question = build_contextual_question(session, user_message, recommended_stage)
    ready_to_close = session.turn_count >= 8 and recommended_stage in {"anxiety", "mood"}

    if risk_level == "urgent":
        reflection = build_contextual_reflection(session, user_message, risk_level)
        next_question = "Voce esta em seguranca neste momento?"
        recommended_stage = "closing"
    else:
        reflection = build_contextual_reflection(session, user_message, risk_level)

    reflection = reduce_repeated_opening(session, reflection)
    support = build_contextual_support(session, user_message, recommended_stage)
    grounded_reply = None if recommended_stage == "closing" else build_grounded_lia_reply(session, user_message)
    assistant_reply = grounded_reply or join_reply_parts(
        reflection,
        support,
        next_question if recommended_stage != "closing" else None,
    )
    assistant_reply = reduce_repeated_first_sentence(session, assistant_reply)
    analysis = LiaAnalysis(
        assistant_reply=assistant_reply,
        reflection=reflection,
        next_question=next_question,
        risk_level=risk_level,
        mood_value=mood_value,
        gad7_scores=gad7_scores,
        phq9_scores=phq9_scores,
        ready_to_close=ready_to_close,
        recommended_stage=recommended_stage,
    )
    return ensure_lia_continuation(session, user_message, analysis)


def refine_lia_analysis(session: LiaSessionState, analysis: LiaAnalysis, user_message: str) -> LiaAnalysis:
    recent_assistant_messages = [normalize_for_match(item) for item in get_recent_transcript_by_role(session, "assistant", 2)]
    has_primary_reply = has_usable_assistant_reply(analysis.assistant_reply or "", recent_assistant_messages)

    if not has_primary_reply:
        raise ValueError("Ollama returned an unusable assistant reply")

    analysis.assistant_reply = normalize_optional_text(analysis.assistant_reply) or analysis.assistant_reply
    if reply_has_therapeutic_style(analysis.assistant_reply):
        raise ValueError("Ollama returned an overly therapeutic assistant reply")
    if reply_misreads_clear_message(session, user_message, analysis.assistant_reply):
        raise ValueError("Ollama misread a clear user message")
    analysis.reflection = normalize_optional_text(analysis.reflection) or analysis.assistant_reply
    analysis.next_question = normalize_optional_text(analysis.next_question)
    normalized_user_message = normalize_optional_text(user_message) or ""
    if normalized_user_message:
        normalized_reply = normalize_for_match(analysis.assistant_reply)
        normalized_user = normalize_for_match(normalized_user_message)
        if normalized_reply.startswith(normalized_user):
            trimmed_reply = analysis.assistant_reply[len(normalized_user_message) :].lstrip(" .:-\n")
            analysis.assistant_reply = trimmed_reply or analysis.assistant_reply

    if scores_look_overfilled(session, analysis, user_message):
        analysis.gad7_scores = [None] * 7
        analysis.phq9_scores = [None] * 9

    inferred_gad_scores, inferred_phq_scores, inferred_mood_value = infer_signal_scores(user_message)
    analysis.gad7_scores = blend_signal_scores(analysis.gad7_scores, inferred_gad_scores)
    analysis.phq9_scores = blend_signal_scores(analysis.phq9_scores, inferred_phq_scores)
    if analysis.mood_value is None:
        analysis.mood_value = inferred_mood_value

    analysis.recommended_stage = infer_effective_stage(session, analysis, user_message)
    strict_support_context = should_require_strict_support_context(session, user_message)

    if not reply_respects_support_context(session, user_message, analysis.assistant_reply):
        rewritten_reply = repair_lia_reply(
            session,
            user_message,
            analysis.assistant_reply,
            analysis.recommended_stage,
            retry_hint=(
                "Reescreva de forma mais adequada ao contexto. Se a fala for leve, simbolica ou so um passo rapido, "
                "nao dramatize, nao investigue sintomas e nao ofereca tarefas."
            ),
        )
        if rewritten_reply and reply_respects_support_context(session, user_message, rewritten_reply):
            analysis.assistant_reply = rewritten_reply
            analysis.reflection = rewritten_reply
        elif (not strict_support_context) and rewritten_reply and has_usable_assistant_reply(
            rewritten_reply, recent_assistant_messages
        ):
            analysis.assistant_reply = rewritten_reply
            analysis.reflection = rewritten_reply
        else:
            raise ValueError("Ollama returned a reply that does not fit support context")

    needs_active_guidance = user_needs_active_guidance(session, user_message)
    strict_active_guidance = context_requires_strict_active_guidance(session, user_message)

    if (
        needs_active_guidance
        and not analysis.ready_to_close
        and analysis.recommended_stage != "closing"
        and not reply_shows_active_guidance(analysis.assistant_reply)
    ):
        rewritten_reply = repair_lia_reply(
            session,
            user_message,
            analysis.assistant_reply,
            analysis.recommended_stage,
            retry_hint=(
                "A resposta precisa tomar iniciativa sem coaching. Traga reconhecimento concreto, uma frase curta de apoio ou presenca "
                "e uma pergunta curta sobre corpo, sono, energia, vontade, humor ou frequencia."
            ),
        )
        if rewritten_reply and reply_shows_active_guidance(rewritten_reply):
            analysis.assistant_reply = rewritten_reply
            analysis.reflection = rewritten_reply
        elif rewritten_reply and reply_shows_supportive_progress(rewritten_reply) and not strict_active_guidance:
            analysis.assistant_reply = rewritten_reply
            analysis.reflection = rewritten_reply
        else:
            raise ValueError("Ollama returned a passive or unsupportive assistant reply")

    if reply_is_too_vague_for_context(session, user_message, analysis.assistant_reply):
        grounded_reply = build_grounded_lia_reply(session, user_message)
        if grounded_reply and has_usable_assistant_reply(grounded_reply, recent_assistant_messages):
            analysis.assistant_reply = grounded_reply
            analysis.reflection = grounded_reply

    return analysis


def context_requires_strict_active_guidance(session: LiaSessionState, user_message: str) -> bool:
    context = build_lia_context(session, user_message)
    return bool(
        context["unwell"]
        or context["energia"]
        or context["sono"]
        or context["tristeza"]
        or context["interesse"]
        or context["worn_out"]
        or context["stuck_without_improvement"]
    )


def analyze_lia_turn(session: LiaSessionState, user_message: str) -> tuple[LiaAnalysis, bool]:
    if LIA_LLM_ENABLED:
        return analyze_lia_turn_with_llm(session, user_message)
    return fallback_lia_analysis(session, user_message), False


def analyze_lia_turn_with_llm(session: LiaSessionState, user_message: str) -> tuple[LiaAnalysis, bool]:
    base_analysis = fallback_lia_analysis(session, user_message)
    try:
        llm_analysis = call_cloud_or_local_lia(session)
        llm_analysis.gad7_scores = blend_signal_scores(llm_analysis.gad7_scores, base_analysis.gad7_scores)
        llm_analysis.phq9_scores = blend_signal_scores(llm_analysis.phq9_scores, base_analysis.phq9_scores)
        if llm_analysis.mood_value is None:
            llm_analysis.mood_value = base_analysis.mood_value
        llm_analysis.ready_to_close = bool(llm_analysis.ready_to_close and base_analysis.ready_to_close)
        llm_analysis.recommended_stage = infer_effective_stage(session, llm_analysis, user_message)
        refined = refine_lia_analysis(session, llm_analysis, user_message)
        return refined, True
    except Exception:
        pass

    try:
        rewritten_reply = rewrite_lia_from_analysis(
            session,
            user_message,
            base_analysis,
            retry_hint=(
                "Mantenha a mesma conducao do roteiro. "
                "So deixe a fala menos quadrada, mais espontanea e mais conversada."
            ),
        )
        if not rewritten_reply:
            return base_analysis, False

        candidate = base_analysis.model_copy(deep=True)
        candidate.assistant_reply = rewritten_reply
        candidate.reflection = rewritten_reply
        candidate.next_question = base_analysis.next_question
        refined = refine_lia_analysis(session, candidate, user_message)
        return refined, True
    except Exception:
        return base_analysis, False


def count_answered_scores(scores: list[int | None]) -> int:
    return sum(1 for value in scores if value is not None)


def infer_mood_value(session: LiaSessionState) -> int:
    if session.mood_value is not None:
        return session.mood_value

    gad_score = sum(score or 0 for score in session.gad7_scores)
    phq_score = sum(score or 0 for score in session.phq9_scores)
    combined = max(gad_score, phq_score)

    if combined >= 15:
        return 2
    if combined >= 8:
        return 3
    return 4


def build_lia_note(transcript: list[LiaTranscriptMessage]) -> str | None:
    user_messages = [
        item.content
        for item in transcript
        if item.role == "user" and is_probably_meaningful_message(item.content, allow_short_contextual=False)
    ]
    if not user_messages:
        return None
    return normalize_optional_text(" | ".join(user_messages)[0:500])


def get_meaningful_user_messages(transcript: list[LiaTranscriptMessage]) -> list[str]:
    return [
        item.content
        for item in transcript
        if item.role == "user" and is_probably_meaningful_message(item.content, allow_short_contextual=False)
    ]


def build_user_facing_topic_summary(session: LiaSessionState, topics: list[str]) -> str:
    text_value = build_memory_source_text(session)
    bullets: list[str] = []

    if contains_any(text_value, ["mud", "novo trabalho", "emprego", "empresa"]):
        bullets.append("mudanca ou pressao no trabalho")
    elif "trabalho ou estudos" in topics:
        bullets.append("trabalho ou estudos apareceram como parte do contexto")

    if "pressao do dia a dia" in topics:
        bullets.append("sensacao de muitas demandas ao mesmo tempo")
    if "sono" in topics:
        bullets.append("sono prejudicado ou descanso insuficiente")
    if "energia" in topics or "humor" in topics:
        bullets.append("queda de energia, animo ou disposicao")
    if "ansiedade" in topics or "corpo em alerta" in topics:
        bullets.append("nervosismo, preocupacao ou corpo em alerta")
    if contains_any(text_value, ["amigos", "sair", "isol", "afastad"]):
        bullets.append("menos vontade de sair ou se aproximar de pessoas")

    if not bullets:
        note = build_lia_note(session.transcript)
        if note:
            return "Ponto trazido no check-in inicial."
        return "Check-in breve registrado pela Lia."

    return "; ".join(list(dict.fromkeys(bullets))[:4]) + "."


def build_memory_source_text(session: LiaSessionState) -> str:
    user_messages = [
        item.content
        for item in session.transcript
        if item.role == "user" and is_probably_meaningful_message(item.content, allow_short_contextual=False)
    ]
    return normalize_for_match(" ".join(user_messages))


def build_opening_context(session: LiaSessionState) -> str | None:
    light_value = normalize_optional_text(session.memory.light_prompt_value)
    if light_value:
        return light_value
    first_user_message = next(
        (
            normalize_optional_text(item.content)
            for item in session.transcript
            if item.role == "user" and normalize_optional_text(item.content)
        ),
        None,
    )
    return first_user_message


def derive_memory_topics(session: LiaSessionState) -> list[str]:
    text_value = build_memory_source_text(session)
    gad_score = sum(score or 0 for score in session.gad7_scores)
    phq_score = sum(score or 0 for score in session.phq9_scores)
    topics: list[str] = []

    if contains_any(text_value, ["ansios", "nervos", "tenso", "panico", "preocup"]) or gad_score >= 5:
        topics.append("ansiedade")
    if contains_any(text_value, ["palpit", "coracao", "acelerado", "taquic", "peito"]) or gad_score >= 8:
        topics.append("corpo em alerta")
    if contains_any(text_value, ["pression", "cobranc", "exigenc", "demanda", "responsabilidade"]):
        topics.append("pressao do dia a dia")
    if contains_any(text_value, ["trabalho", "estudo", "faculdade", "prova", "chefe", "empresa", "emprego", "servico"]):
        topics.append("trabalho ou estudos")
    if contains_any(text_value, ["terminei", "terminou", "namoro", "relacionamento", "separ", "rompimento", "saudade"]):
        topics.append("relacionamentos")
    if contains_any(text_value, ["sono", "dorm", "inson", "acordo"]):
        topics.append("sono")
    if contains_any(text_value, ["energia", "cansad", "exaust", "fadiga", "sem energia"]) or phq_score >= 8:
        topics.append("energia")
    if contains_any(text_value, ["triste", "vazio", "desanim", "sem vontade", "sem esperanca"]) or phq_score >= 5:
        topics.append("humor")
    if contains_any(text_value, ["sozinh", "isol", "afastad"]):
        topics.append("solidao")

    return list(dict.fromkeys(topics))[:6]


def build_recent_memory_summary(session: LiaSessionState, topics: list[str]) -> str | None:
    parts: list[str] = []

    if "pressao do dia a dia" in topics and "trabalho ou estudos" in topics:
        parts.append("a pressao do trabalho ou dos estudos apareceu com forca")
    elif "pressao do dia a dia" in topics:
        parts.append("a pressao do dia a dia voltou a pesar")

    if "ansiedade" in topics and "corpo em alerta" in topics:
        parts.append("a ansiedade apareceu tanto nos pensamentos quanto no corpo")
    elif "ansiedade" in topics:
        parts.append("a ansiedade pediu mais espaco para ser cuidada")

    if "relacionamentos" in topics:
        parts.append("relacionamentos entraram como parte importante do contexto")
    if "sono" in topics and "energia" in topics:
        parts.append("sono e energia tambem mereceram atencao")
    elif "sono" in topics:
        parts.append("o sono apareceu como um ponto sensivel")
    elif "energia" in topics:
        parts.append("a energia ficou mais baixa do que o ideal")
    if "humor" in topics:
        parts.append("o humor tambem pareceu mais pesado")

    if not parts:
        note = build_lia_note(session.transcript)
        if not note:
            return None
        return "voce compartilhou um retrato inicial importante sobre como vem se sentindo"

    return ", ".join(parts[:3])


def build_memory_summary(topics: list[str]) -> str | None:
    if not topics:
        return None

    if len(topics) == 1:
        return f"Um tema que costuma merecer cuidado por aqui e {topics[0]}."
    if len(topics) == 2:
        return f"Temas que costumam voltar por aqui: {topics[0]} e {topics[1]}."

    return "Temas que costumam voltar por aqui: " + ", ".join(topics[:3]) + "."


def build_interaction_summary(session: LiaSessionState, topics: list[str]) -> str:
    return build_user_facing_topic_summary(session, topics)


def get_topic_state_value(session: LiaSessionState, key: str) -> str | None:
    state = session.topic_states.get(key)
    if not state or not state.filled:
        return None
    return normalize_optional_text(state.value)


def triage_status(value: str | None) -> str:
    return "informado" if normalize_optional_text(value) else "pendente"


def build_lia_triage_form(session: LiaSessionState, topics: list[str]) -> dict[str, Any]:
    text_value = build_memory_source_text(session)
    user_messages = get_meaningful_user_messages(session.transcript)
    gad_score = sum(score or 0 for score in session.gad7_scores)
    phq_score = sum(score or 0 for score in session.phq9_scores)

    symptoms: list[str] = []
    symptom_rules = [
        ("ansiedade, preocupacao ou tensao", ["ansios", "preocup", "nervos", "tenso"]),
        ("corpo em alerta ou sintomas fisicos", ["palpit", "coracao", "acelerado", "peito", "respirar", "falta de ar"]),
        ("sono prejudicado ou exaustao", ["sono", "dorm", "inson", "exaust"]),
        ("queda de energia ou cansaco", ["energia", "cansad", "cansaco", "fadiga"]),
        ("desanimo, tristeza ou apatia", ["triste", "desanim", "sem vontade", "apatia", "vazio"]),
        ("irritabilidade ou raiva", ["irrit", "raiva", "sem paciencia"]),
        ("isolamento ou afastamento social", ["isol", "afastad", "evitado meus amigos", "ficar sozinho"]),
        ("procrastinacao, tarefas travadas ou dificuldade de foco", ["procrast", "trav", "nao consigo focar", "foco", "tarefas"]),
        ("sentimento de culpa ou fracasso", ["culpa", "fracasso", "bobo", "insuficiente"]),
    ]
    for label, fragments in symptom_rules:
        if contains_any(text_value, fragments):
            symptoms.append(label)

    risk_items: list[str] = []
    if contains_any(text_value, ["morrer", "me matar", "suicid", "nao queria estar aqui", "sumir", "me machucar"]):
        risk_items.append("fala que exige checagem de seguranca")
    if contains_any(text_value, ["automutil", "autoles", "me corto", "me machuco"]):
        risk_items.append("possivel autolesao mencionada")
    if contains_any(text_value, ["agredir", "bater em alguem", "machucar alguem", "violencia"]):
        risk_items.append("agressividade contra terceiros mencionada")
    if contains_any(text_value, ["alcool", "bebida", "maconha", "cigarro", "droga", "tarja preta"]):
        risk_items.append("uso de substancia mencionado")
    if contains_any(text_value, ["alucin", "delirio", "ouvindo vozes", "vozes"]):
        risk_items.append("possivel episodio psicotico mencionado")

    previous_help = None
    if contains_any(text_value, ["psicolog", "terapia", "terapeuta", "consulta", "triagem", "psiquiatr"]):
        previous_help = "mencionou contato, duvida ou encaminhamento para atendimento profissional"

    medication = None
    if contains_any(text_value, ["remedio", "medicacao", "medicamento", "psiquiatrica", "tarja preta"]):
        medication = "mencao a medicacao; confirmar detalhes em triagem profissional"

    support_network = None
    if contains_any(text_value, ["amigos", "familia", "filho", "mae", "pai", "sozinh", "sozinha", "apoio"]):
        support_network = "houve mencao a pessoas proximas ou sensacao de apoio/isolamento; confirmar rede de apoio"

    routine_items: list[str] = []
    if contains_any(text_value, ["sono", "dorm", "inson", "acordo"]):
        routine_items.append("sono")
    if contains_any(text_value, ["trabalho", "emprego", "faculdade", "estudo", "prova", "tarefas"]):
        routine_items.append("trabalho/estudo")
    if contains_any(text_value, ["amigos", "sair", "isol", "afastad", "ficar sozinho"]):
        routine_items.append("interacoes sociais")
    if contains_any(text_value, ["fome", "apetite", "comer"]):
        routine_items.append("apetite")

    expectation = None
    if contains_any(text_value, ["quero ajuda", "preciso de ajuda", "nao sei o que fazer", "me ajuda"]):
        expectation = "busca ajuda para organizar o que esta sentindo e pensar em proximos passos"
    elif contains_any(text_value, ["psicolog", "consulta", "triagem"]):
        expectation = "apresenta duvidas ou expectativa em relacao ao atendimento profissional"

    form = {
        "motivo_procura": {
            "label": "Motivo da procura",
            "value": get_topic_state_value(session, "main_focus") or (user_messages[0] if user_messages else None),
        },
        "inicio_sintomas": {
            "label": "Inicio ou duracao",
            "value": get_topic_state_value(session, "frequency_duration"),
        },
        "sintomas_atuais": {
            "label": "Sintomas atuais relatados/observados",
            "value": symptoms or topics or None,
        },
        "impacto_rotina": {
            "label": "Impacto na rotina",
            "value": get_topic_state_value(session, "functional_impact") or (", ".join(routine_items) if routine_items else None),
        },
        "contexto_social": {
            "label": "Interacoes sociais e rede de apoio",
            "value": support_network,
        },
        "ajuda_anterior": {
            "label": "Ajuda ou acompanhamento previo",
            "value": previous_help,
        },
        "medicacao": {
            "label": "Medicacao ou acompanhamento psiquiatrico",
            "value": medication,
        },
        "risco": {
            "label": "Risco e pontos de atencao",
            "value": risk_items or ("sem sinal de risco registrado na conversa" if user_messages else None),
        },
        "expectativa": {
            "label": "Expectativa com atendimento",
            "value": expectation,
        },
        "disponibilidade": {
            "label": "Disponibilidade para atendimento",
            "value": "definida no agendamento da triagem" if session.completed else None,
        },
    }

    for item in form.values():
        value = item["value"]
        if isinstance(value, list):
            item["status"] = "informado" if value else "pendente"
        else:
            item["status"] = triage_status(value)

    form["observacoes_lia"] = {
        "label": "Observacoes da Lia",
        "value": build_user_facing_topic_summary(session, topics),
        "status": "informado",
    }
    form["indicadores"] = {
        "label": "Indicadores internos",
        "value": {
            "gad7_parcial": gad_score,
            "phq9_parcial": phq_score,
            "humor_inferido": infer_mood_value(session),
        },
        "status": "apoio",
    }
    return form


def build_psychologist_report(session: LiaSessionState, topics: list[str]) -> str:
    user_messages = get_meaningful_user_messages(session.transcript)
    first_message = normalize_optional_text(user_messages[0]) if user_messages else None
    later_messages = [message for message in user_messages[1:] if normalize_optional_text(message)]
    mood_value = infer_mood_value(session)
    mood_label = {
        1: "muito baixo",
        2: "baixo",
        3: "intermediario",
        4: "mais estavel",
        5: "positivo",
    }.get(mood_value, "intermediario")

    parts: list[str] = []
    summary = build_user_facing_topic_summary(session, topics)
    parts.append(f"Sintese inicial: {summary}")
    if first_message and len(first_message) <= 180:
        parts.append(f"Frase inicial registrada: {first_message}.")
    elif first_message:
        parts.append("A primeira fala trouxe um relato amplo de desconforto e necessidade de orientacao.")
    if later_messages:
        parts.append(f"Pontos nomeados depois: {'; '.join(later_messages[:3])}.")
    if topics:
        parts.append(f"Temas que apareceram: {', '.join(topics[:4])}.")
    parts.append(f"Humor inferido ao fim da conversa: {mood_label}.")

    if session.pause_used:
        parts.append("Houve uma pausa leve com permissao do usuario para aliviar o ritmo da conversa.")

    gad_score = sum(score or 0 for score in session.gad7_scores)
    phq_score = sum(score or 0 for score in session.phq9_scores)
    if gad_score >= 8 or phq_score >= 8:
        attention_items: list[str] = []
        if gad_score >= 8:
            attention_items.append("ansiedade")
        if phq_score >= 8:
            attention_items.append("humor e energia")
        parts.append(f"Pontos que merecem atencao no acompanhamento: {', '.join(attention_items)}.")

    return " ".join(parts)


def save_lia_interaction(
    db: Session,
    current_user: User,
    session: LiaSessionState,
    topics: list[str],
) -> LiaInteraction:
    interaction: LiaInteraction | None = None
    if session.active_interaction_id:
        interaction = db.get(LiaInteraction, session.active_interaction_id)

    if interaction is None:
        interaction = LiaInteraction(
            usuario_id=current_user.id,
            session_key=session.session_key,
        )

    interaction.opening_label = normalize_optional_text(session.memory.light_prompt_label)
    interaction.opening_value = normalize_optional_text(session.memory.light_prompt_value)
    interaction.summary = build_interaction_summary(session, topics)
    interaction.report = build_psychologist_report(session, topics)
    interaction.triage_form = build_lia_triage_form(session, topics)
    interaction.transcript = serialize_lia_transcript(session.transcript)
    interaction.topics = topics
    interaction.mood_value = infer_mood_value(session)
    interaction.status = "final" if session.completed else "draft"
    interaction.finalized = bool(session.completed)
    db.add(interaction)
    db.flush()
    session.active_interaction_id = interaction.id
    return interaction


def save_lia_session_draft(db: Session, current_user: User, session: LiaSessionState) -> bool:
    if session.completed:
        return False

    topics = derive_memory_topics(session)
    save_lia_interaction(db, current_user, session, topics)
    db.commit()
    return True


def merge_memory_topics(existing_topics: list[str], new_topics: list[str]) -> list[str]:
    merged = [str(item) for item in new_topics if str(item).strip()]
    for item in existing_topics:
        topic = str(item).strip()
        if topic and topic not in merged:
            merged.append(topic)
    return merged[:6]


def upsert_lia_memory(db: Session, current_user: User, session: LiaSessionState) -> LiaMemorySnapshot:
    memory = db.get(LiaUserMemory, current_user.id)
    if memory is None:
        memory = LiaUserMemory(usuario_id=current_user.id, topicos=[], total_conversas=0)

    new_topics = derive_memory_topics(session)
    merged_topics = merge_memory_topics(memory.topicos or [], new_topics)
    recent_summary = build_recent_memory_summary(session, new_topics)
    summary = build_memory_summary(merged_topics)

    memory.topicos = merged_topics
    memory.resumo = summary
    memory.resumo_recente = recent_summary
    memory.total_conversas = int(memory.total_conversas or 0) + 1
    memory.ultimo_humor_valor = infer_mood_value(session)
    memory.primeiro_contato_concluido = True
    memory.atualizado_em = utcnow()

    db.add(memory)
    recent_interactions = list_recent_lia_interactions(db, current_user.id, finalized_only=True)
    snapshot = build_lia_memory_snapshot(memory, recent_interactions)
    session.memory = snapshot
    return snapshot


def save_lia_session_results(db: Session, current_user: User, session: LiaSessionState) -> bool:
    refresh_dashboard = False

    if "gad7" not in session.saved_questionnaires:
        respostas = [score or 0 for score in session.gad7_scores]
        result = QuestionnaireResult(
            usuario_id=current_user.id,
            tipo="gad7",
            respostas=respostas,
            pontuacao=sum(respostas),
            classificacao=classify_score("gad7", sum(respostas)),
        )
        db.add(result)
        session.saved_questionnaires.append("gad7")
        refresh_dashboard = True

    if "phq9" not in session.saved_questionnaires:
        respostas = [score or 0 for score in session.phq9_scores]
        result = QuestionnaireResult(
            usuario_id=current_user.id,
            tipo="phq9",
            respostas=respostas,
            pontuacao=sum(respostas),
            classificacao=classify_score("phq9", sum(respostas)),
        )
        db.add(result)
        session.saved_questionnaires.append("phq9")
        refresh_dashboard = True

    if not session.saved_mood:
        mood = MoodEntry(
            usuario_id=current_user.id,
            valor=infer_mood_value(session),
            nota=build_lia_note(session.transcript),
        )
        db.add(mood)
        session.saved_mood = True
        refresh_dashboard = True

    topics = derive_memory_topics(session)
    save_lia_interaction(db, current_user, session, topics)
    upsert_lia_memory(db, current_user, session)
    refresh_dashboard = True

    if refresh_dashboard:
        db.commit()

    return refresh_dashboard


def build_lia_closing_messages(session: LiaSessionState, risk_level: Literal["none", "attention", "urgent"]) -> list[str]:
    if risk_level == "urgent" or (session.phq9_scores[-1] or 0) > 0:
        return [
            "Antes de qualquer outra coisa, sua seguranca vem primeiro.",
            "Se existir risco agora, procure ajuda presencial imediata ou alguem de confianca perto de voce.",
        ]

    gad_score = sum(score or 0 for score in session.gad7_scores)
    phq_score = sum(score or 0 for score in session.phq9_scores)

    if gad_score >= 10 and phq_score >= 10:
        return [
            "Percebi sinais de ansiedade e cansaco emocional que merecem cuidado nas proximas semanas.",
            "Para hoje, tente escolher uma pausa real e um apoio humano simples, como avisar alguem de confianca que o dia esta pesado.",
        ]

    if gad_score >= 10:
        return [
            "Percebi sinais de ansiedade que merecem atencao e pequenas pausas ao longo dos dias.",
            "Se puder, vale fazer uma pausa curta de respiracao e reduzir a cobranca para o proximo bloco do dia.",
        ]

    if phq_score >= 10:
        return [
            "Percebi sinais de humor mais rebaixado e pouca energia nos ultimos dias.",
            "Hoje, talvez ajude escolher so uma tarefa pequena e avisar alguem de confianca que voce nao esta no seu melhor ritmo.",
        ]

    return [
        "Obrigada por conversar comigo. Por hoje, voce nao precisa resolver tudo de uma vez.",
        "Se fizer sentido, escolha um cuidado simples para agora e deixe o resto para continuar com mais apoio.",
    ]


def build_simple_closing_reply(session: LiaSessionState, user_message: str) -> str:
    context = build_lia_context(session, user_message)
    if context["quick_pass"] or context["no_issue"]:
        return "Tudo certo. Se por hoje ja deu, a gente pode parar por aqui. E, se voce sentir vontade, ainda pode continuar conversando comigo um pouco mais."
    if context["wants_to_stop"]:
        return "Tudo bem. A gente pode parar por aqui hoje. Obrigada por dividir isso comigo. Se depois voce quiser retomar, eu continuo daqui com voce."

    if session.followup_mode and (session.followup_turns_left or 0) <= 0:
        return (
            "Obrigada por continuar comigo mais um pouco. Pelo que voce trouxe, faz sentido nao deixar isso so com voce. "
            "Um bom proximo passo pode ser seguir para a triagem com um dos nossos profissionais, levando essa conversa como ponto de partida. "
            "Se for encerrar agora, tenta escolher uma coisa simples para baixar um pouco o ritmo, como ouvir algo calmo ou se afastar por alguns minutos das demandas. "
            "Cuida de voce; quando voltar, eu continuo de onde isso ficou."
        )

    return (
        "Obrigada por me contar isso. Ja temos um bom ponto de partida para organizar essa conversa. "
        "Se fizer sentido, voce pode seguir para a triagem; se ainda tiver algo importante, tambem pode continuar comigo um pouco mais."
    )


def build_followup_continuation_reply(session: LiaSessionState, user_message: str) -> str:
    context = build_lia_context(session, user_message)
    if not is_probably_meaningful_message(user_message, allow_short_contextual=False):
        return (
            "Nao consegui pegar bem essa ultima parte. Se ainda tiver algo importante, me conta com um pouco mais de contexto. "
            "Se foi so uma resposta solta, tudo bem tambem; a gente pode parar por aqui por hoje."
        )
    if context["asks_about_professional"]:
        return (
            "Pode ajudar, sim. Conversar com um profissional pode ser um jeito de olhar para isso com mais calma, "
            "organizar o que esta acontecendo e pensar em proximos passos que facam sentido para voce. "
            "Nao precisa chegar la com tudo pronto; falar exatamente essa duvida ja e um bom comeco."
        )
    if context["sono"] or context["energia"]:
        return "Isso ajuda a completar melhor o que voce estava dizendo. Quando isso aparece em casa, o que costuma te dar algum alivio, mesmo que pequeno?"
    if context["irritabilidade"]:
        return "Essa irritacao junto com o afastamento parece ser uma parte importante do que ficou. Quando voce percebe isso acontecendo, costuma ser mais vontade de ficar quieto ou falta de paciencia com as pessoas?"
    if context["controlar"] or context["ansiedade"]:
        return "Essa cabeca que nao desliga parece estar acompanhando voce depois do trabalho tambem. O que costuma ficar repetindo mais quando voce chega em casa?"
    return "Pode me contar so mais esse pedaco. O que voce acha importante a Lia guardar sobre isso?"


def reply_sounds_like_closing(reply: str | None) -> bool:
    lowered = normalize_for_match(reply)
    return contains_any(
        lowered,
        [
            "quer encerrar",
            "fechar por aqui",
            "parar por aqui",
            "podemos fechar",
            "ja consegui montar um retrato",
            "ja consegui guardar o essencial",
            "por hoje, talvez ja seja suficiente",
            "acho importante que voce nao fique carregando",
        ],
    )


def ensure_database_shape() -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    statements: list[str] = []

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "consentimento_lgpd" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN consentimento_lgpd BOOLEAN NOT NULL DEFAULT 1")
    if "role" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN role VARCHAR NOT NULL DEFAULT 'user'")
    if "professional_email_encrypted" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN professional_email_encrypted TEXT")
    if "professional_name_encrypted" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN professional_name_encrypted TEXT")

    if "lia_interactions" in inspector.get_table_names():
        lia_columns = {column["name"] for column in inspector.get_columns("lia_interactions")}
        if "session_key" not in lia_columns:
            statements.append("ALTER TABLE lia_interactions ADD COLUMN session_key VARCHAR")
        if "status" not in lia_columns:
            statements.append("ALTER TABLE lia_interactions ADD COLUMN status VARCHAR NOT NULL DEFAULT 'final'")
        if "finalized" not in lia_columns:
            statements.append("ALTER TABLE lia_interactions ADD COLUMN finalized BOOLEAN NOT NULL DEFAULT 1")
        if "transcript" not in lia_columns:
            statements.append("ALTER TABLE lia_interactions ADD COLUMN transcript JSON NOT NULL DEFAULT '[]'")
        if "triage_form" not in lia_columns:
            statements.append("ALTER TABLE lia_interactions ADD COLUMN triage_form JSON")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))


def sync_professional_encryption(db: Session) -> None:
    psychologists = db.scalars(select(User).where(User.role == "psychologist")).all()
    changed = False
    for psychologist in psychologists:
        encrypted_email = encrypt_text(psychologist.email)
        encrypted_name = encrypt_text(psychologist.nome)
        if psychologist.professional_email_encrypted != encrypted_email:
            psychologist.professional_email_encrypted = encrypted_email
            changed = True
        if psychologist.professional_name_encrypted != encrypted_name:
            psychologist.professional_name_encrypted = encrypted_name
            changed = True
        if changed:
            db.add(psychologist)
    if changed:
        db.commit()


def set_professional_private_fields(user: User, email: str, name: str) -> None:
    user.professional_email_encrypted = encrypt_text(email)
    user.professional_name_encrypted = encrypt_text(name)


def build_admin_psychologist_out(user: User) -> UsuarioOut:
    return UsuarioOut(
        id=user.id,
        email=decrypt_text(user.professional_email_encrypted) or user.email,
        nome=decrypt_text(user.professional_name_encrypted) or user.nome,
        role="psychologist",
        consentimento_lgpd=user.consentimento_lgpd,
        criado_em=user.criado_em,
    )


def seed_contents(db: Session) -> None:
    existing = db.scalar(select(EducationalContent.id).limit(1))
    if existing is not None:
        return

    for item in SEEDED_CONTENTS:
        db.add(EducationalContent(**item))
    db.commit()


def ensure_initial_admin(db: Session) -> None:
    configured_admin_emails = set(ADMIN_EMAILS)
    if configured_admin_emails:
        users = db.scalars(select(User).where(User.email.in_(configured_admin_emails))).all()
        for user in users:
            user.role = "admin"
            db.add(user)
        if users:
            db.commit()

    admin_exists = db.scalar(select(User.id).where(User.role == "admin").limit(1))
    if admin_exists:
        return

    first_user = db.scalar(select(User).order_by(User.criado_em.asc()).limit(1))
    if first_user:
        first_user.role = "admin"
        db.add(first_user)
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_database_shape()
    with SessionLocal() as db:
        ensure_initial_admin(db)
        sync_professional_encryption(db)
        seed_contents(db)
    yield


app = FastAPI(
    title="Mental Health API",
    description="API de apoio a saude mental com autenticacao, triagens e acompanhamento.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_verification_code(value: str) -> str:
    cleaned = re.sub(r"\D", "", value or "")
    if len(cleaned) != 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe um codigo de 6 digitos.")
    return cleaned


def hash_verification_code(email: str, purpose: str, code: str) -> str:
    return sha256(f"{normalize_email(email)}:{purpose}:{code}".encode("utf-8")).hexdigest()


def smtp_is_configured() -> bool:
    placeholder_values = {
        "",
        "seu-email@gmail.com",
        "sua-senha-de-app",
    }
    return bool(
        SMTP_HOST
        and SMTP_FROM_EMAIL not in placeholder_values
        and SMTP_USERNAME not in placeholder_values
        and SMTP_PASSWORD not in placeholder_values
    )


def resend_is_configured() -> bool:
    placeholder_values = {
        "",
        "re_xxxxxxxxx",
    }
    return bool(
        RESEND_API_KEY not in placeholder_values
        and RESEND_FROM_EMAIL not in placeholder_values
    )


def build_verification_email_subject(purpose: str) -> str:
    if purpose == "register":
        return "Codigo de verificacao para cadastro"
    if purpose == "login":
        return "Codigo de verificacao para login"
    if purpose == "reset":
        return "Codigo de verificacao para redefinir sua senha"
    return "Codigo de verificacao"


def build_verification_email_body(code: str, purpose: str) -> str:
    if purpose == "register":
        action_label = "concluir seu cadastro"
    elif purpose == "login":
        action_label = "entrar na sua conta"
    elif purpose == "reset":
        action_label = "redefinir sua senha"
    else:
        action_label = "continuar na sua conta"
    return (
        "Seu codigo de verificacao do Mental Health App e:\n\n"
        f"{code}\n\n"
        f"Use este codigo para {action_label}.\n"
        f"Ele expira em {EMAIL_VERIFICATION_CODE_TTL_MINUTES} minutos.\n\n"
        "Se voce nao pediu este codigo, ignore este email."
    )


def send_verification_email_via_resend(email: str, code: str, purpose: str) -> None:
    if not resend_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O envio por Resend ainda nao foi configurado no servidor.",
        )

    payload = {
        "from": f"{RESEND_FROM_NAME} <{RESEND_FROM_EMAIL}>",
        "to": [normalize_email(email)],
        "subject": build_verification_email_subject(purpose),
        "text": build_verification_email_body(code, purpose),
        "html": (
            "<p>Seu codigo de verificacao do Mental Health App e:</p>"
            f"<p style=\"font-size:28px;font-weight:700;letter-spacing:4px;\">{code}</p>"
            f"<p>Use este codigo para "
            f"{'concluir seu cadastro' if purpose == 'register' else 'entrar na sua conta' if purpose == 'login' else 'redefinir sua senha'}."
            f" Ele expira em {EMAIL_VERIFICATION_CODE_TTL_MINUTES} minutos.</p>"
            "<p>Se voce nao pediu este codigo, ignore este email.</p>"
        ),
    }

    request = urllib_request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "mental-health-app/1.0",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=20) as response:
            if response.status not in {200, 201, 202}:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="O provedor de email recusou o envio do codigo.",
                )
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 401:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Falha ao autenticar no Resend. Confira a chave da API configurada.",
            ) from exc
        if exc.code == 403:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"O Resend recusou por permissao/remetente. {body[:220]}".strip(),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"O Resend recusou o envio do email. {body[:180]}".strip(),
        ) from exc
    except (TimeoutError, urllib_error.URLError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nao foi possivel conectar ao Resend. Confira o acesso de rede.",
        ) from exc


def send_verification_email(email: str, code: str, purpose: str) -> None:
    if resend_is_configured():
        send_verification_email_via_resend(email, code, purpose)
        return

    if not smtp_is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O envio de email ainda nao foi configurado no servidor.",
        )

    message = EmailMessage()
    message["Subject"] = build_verification_email_subject(purpose)
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = normalize_email(email)
    message.set_content(build_verification_email_body(code, purpose))

    try:
        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
            return

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Falha ao autenticar no servidor de email. Confira o usuario e a senha de app do Gmail.",
        ) from exc
    except (TimeoutError, socket.timeout, ConnectionError, OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nao foi possivel conectar ao servidor de email. Confira SMTP, firewall ou acesso de rede.",
        ) from exc


def create_email_verification_code(db: Session, email: str, purpose: str) -> str:
    normalized_email = normalize_email(email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = utcnow()

    db.query(EmailVerificationCode).filter(
        EmailVerificationCode.email == normalized_email,
        EmailVerificationCode.purpose == purpose,
        EmailVerificationCode.consumed_at.is_(None),
    ).update({"consumed_at": now}, synchronize_session=False)

    verification = EmailVerificationCode(
        email=normalized_email,
        purpose=purpose,
        code_hash=hash_verification_code(normalized_email, purpose, code),
        expires_at=now + timedelta(minutes=EMAIL_VERIFICATION_CODE_TTL_MINUTES),
    )
    db.add(verification)
    db.commit()
    return code


def consume_email_verification_code(db: Session, email: str, purpose: str, code: str) -> None:
    normalized_email = normalize_email(email)
    normalized_code = normalize_verification_code(code)
    verification = db.scalar(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == normalized_email)
        .where(EmailVerificationCode.purpose == purpose)
        .where(EmailVerificationCode.consumed_at.is_(None))
        .order_by(EmailVerificationCode.created_at.desc())
    )
    if not verification:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Primeiro solicite um codigo de verificacao para este email.",
        )

    if ensure_utc(verification.expires_at) < utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O codigo expirou. Solicite outro.")

    if verification.code_hash != hash_verification_code(normalized_email, purpose, normalized_code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Codigo de verificacao invalido.")

    verification.consumed_at = utcnow()
    db.add(verification)
    db.commit()


def create_access_token(subject: str) -> str:
    expires_at = utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def has_role(user: User, *roles: str) -> bool:
    user_role = normalize_optional_text(getattr(user, "role", None)) or "user"
    if user.email in ADMIN_EMAILS:
        user_role = "admin"
    return user_role in roles


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nao foi possivel validar as credenciais.",
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = get_user_by_email(db, email)
    if not user:
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso permitido apenas para ADM.")
    return current_user


def require_psychologist_or_admin(current_user: User = Depends(get_current_user)) -> User:
    if not has_role(current_user, "psychologist", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso permitido apenas para psicologo ou ADM.",
        )
    return current_user


def validate_questionnaire_submission(tipo: str, respostas: list[int]) -> dict[str, Any]:
    config = QUESTIONNAIRE_CONFIG.get(tipo)
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionario nao encontrado.")

    if len(respostas) != config["question_count"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Este questionario exige {config['question_count']} respostas.",
        )

    if any(answer < 0 or answer > 3 for answer in respostas):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="As respostas devem usar valores de 0 a 3.",
        )

    return config


def classify_score(tipo: str, pontuacao: int) -> str:
    config = QUESTIONNAIRE_CONFIG[tipo]
    for start, end, label in config["severity"]:
        if start <= pontuacao <= end:
            return label
    return "Sem classificacao"


def latest_result_by_type(results: list[QuestionnaireResult], tipo: str) -> QuestionnaireResult | None:
    for result in results:
        if result.tipo == tipo:
            return result
    return None


def content_priority_score(
    content: EducationalContent,
    latest_phq9: QuestionnaireResult | None,
    latest_gad7: QuestionnaireResult | None,
    latest_mood: MoodEntry | None,
) -> int:
    score = 0

    if content.questionario_tipo == "phq9" and latest_phq9:
        score += latest_phq9.pontuacao
    if content.questionario_tipo == "gad7" and latest_gad7:
        score += latest_gad7.pontuacao

    if content.nivel == "alto":
        score += 3
    elif content.nivel == "moderado":
        score += 2
    else:
        score += 1

    if latest_mood and latest_mood.valor <= 2:
        score += 1

    return score


def build_recommendations(
    latest_mood: MoodEntry | None,
    latest_phq9: QuestionnaireResult | None,
    latest_gad7: QuestionnaireResult | None,
) -> list[RecommendationOut]:
    recommendations: list[RecommendationOut] = []

    if latest_phq9 and latest_phq9.pontuacao >= 15:
        recommendations.append(
            RecommendationOut(
                titulo="Buscar apoio profissional",
                descricao=(
                    "O ultimo resultado do PHQ-9 indica sofrimento relevante. Considere buscar psicologo, "
                    "psiquiatra, CAPS ou outro servico de saude para uma avaliacao profissional."
                ),
                prioridade="alta",
            )
        )
    elif latest_phq9 and latest_phq9.pontuacao >= 10:
        recommendations.append(
            RecommendationOut(
                titulo="Acompanhar humor com mais frequencia",
                descricao=(
                    "Seu rastreio sugere sintomas moderados. Vale registrar humor diariamente e observar "
                    "impactos em sono, energia, concentracao e rotina."
                ),
                prioridade="media",
            )
        )

    if latest_gad7 and latest_gad7.pontuacao >= 15:
        recommendations.append(
            RecommendationOut(
                titulo="Criar plano rapido para momentos de crise",
                descricao=(
                    "Sua pontuacao recente sugere ansiedade intensa. Deixe anotadas estrategias de respiracao, "
                    "pessoas de apoio e servicos de saude acessiveis em caso de piora."
                ),
                prioridade="alta",
            )
        )
    elif latest_gad7 and latest_gad7.pontuacao >= 10:
        recommendations.append(
            RecommendationOut(
                titulo="Incluir tecnicas de regulacao na rotina",
                descricao=(
                    "Praticas como respiracao guiada, pausas entre tarefas e reducao de estimulos antes de dormir "
                    "podem ajudar a baixar o nivel basal de ansiedade."
                ),
                prioridade="media",
            )
        )

    if latest_mood and latest_mood.valor <= 2:
        recommendations.append(
            RecommendationOut(
                titulo="Registrar contexto emocional",
                descricao=(
                    "Seu ultimo humor ficou na faixa baixa. Adicione notas sobre gatilhos, sono, carga de estudo "
                    "ou trabalho e pessoas envolvidas para identificar padroes com mais clareza."
                ),
                prioridade="media",
            )
        )

    if not recommendations:
        recommendations.append(
            RecommendationOut(
                titulo="Manter rotina de acompanhamento",
                descricao=(
                    "Continue registrando humor e realizando triagens periodicas. O valor do app cresce quando "
                    "voce observa os dados ao longo do tempo."
                ),
                prioridade="baixa",
            )
        )

    if latest_phq9 and latest_phq9.respostas and latest_phq9.respostas[-1] > 0:
        recommendations.insert(
            0,
            RecommendationOut(
                titulo="Atencao para seguranca emocional",
                descricao=(
                    "A ultima questao do PHQ-9 sugere sofrimento importante. Se houver risco imediato, procure "
                    "apoio presencial ou servico de emergencia da sua regiao."
                ),
                prioridade="alta",
            ),
        )

    return recommendations[:4]


def get_featured_contents(
    db: Session,
    latest_mood: MoodEntry | None,
    latest_phq9: QuestionnaireResult | None,
    latest_gad7: QuestionnaireResult | None,
) -> list[EducationalContent]:
    contents = db.scalars(select(EducationalContent).order_by(EducationalContent.titulo.asc())).all()
    ranked = sorted(
        contents,
        key=lambda item: content_priority_score(item, latest_phq9, latest_gad7, latest_mood),
        reverse=True,
    )
    return ranked[:4]


def build_triage_request_out(request: TriageRequest | None) -> TriageRequestOut | None:
    if request is None:
        return None
    return TriageRequestOut(
        id=request.id,
        status=request.status,
        psychologist_name=normalize_optional_text(request.psychologist_name),
        notes=normalize_optional_text(request.notes),
        requested_at=ensure_utc(request.requested_at),
        scheduled_for=ensure_utc(request.scheduled_for) if request.scheduled_for else None,
        slot_id=request.slot_id,
        lia_interaction_id=request.lia_interaction_id,
    )


def build_psychologist_triage_request_out(
    request: TriageRequest,
    user: User,
    interaction: LiaInteraction | None,
) -> PsychologistTriageRequestOut:
    return PsychologistTriageRequestOut(
        id=request.id,
        status=request.status,
        requested_at=ensure_utc(request.requested_at),
        scheduled_for=ensure_utc(request.scheduled_for) if request.scheduled_for else None,
        psychologist_name=normalize_optional_text(request.psychologist_name),
        notes=normalize_optional_text(request.notes),
        user=UsuarioOut.model_validate(user),
        interaction=build_lia_recent_interaction(interaction) if interaction else None,
    )


def psychologist_can_access_request(current_user: User, request: TriageRequest) -> bool:
    if has_role(current_user, "admin"):
        return True
    if request.status == "pending":
        return True
    return normalize_optional_text(request.psychologist_name) == normalize_optional_text(current_user.nome)


def build_psychologist_note_out(
    note: PsychologistPatientNote | None,
    request_id: str,
    patient_id: str,
    psychologist_id: str | None = None,
) -> PsychologistPatientNoteOut:
    if note is None:
        return PsychologistPatientNoteOut(
            request_id=request_id,
            patient_id=patient_id,
            psychologist_id=psychologist_id,
            content="",
        )

    return PsychologistPatientNoteOut(
        id=note.id,
        request_id=note.request_id,
        patient_id=note.patient_id,
        psychologist_id=note.psychologist_id,
        content=note.content or "",
        created_at=ensure_utc(note.created_at),
        updated_at=ensure_utc(note.updated_at),
    )


def get_accessible_triage_row(
    db: Session,
    request_id: str,
    current_user: User,
) -> tuple[TriageRequest, User, LiaInteraction | None]:
    row = db.execute(
        select(TriageRequest, User, LiaInteraction)
        .join(User, TriageRequest.usuario_id == User.id)
        .outerjoin(LiaInteraction, TriageRequest.lia_interaction_id == LiaInteraction.id)
        .where(TriageRequest.id == request_id)
    ).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido de triagem nao encontrado.")

    request, patient, interaction = row
    if not psychologist_can_access_request(current_user, request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voce nao tem acesso a este paciente.")
    return request, patient, interaction


def get_current_triage_request(db: Session, user_id: str) -> TriageRequest | None:
    return db.scalar(
        select(TriageRequest)
        .where(TriageRequest.usuario_id == user_id)
        .order_by(TriageRequest.requested_at.desc())
        .limit(1)
    )


def ensure_triage_slots(db: Session) -> None:
    # Legacy fallback: only seed automatic slots when no psychologist has configured
    # future availability yet. Once professionals customize their agenda, patient
    # choices come directly from those slots.
    configured_future_slot = db.scalar(
        select(PsychologistSlot.id)
        .where(PsychologistSlot.starts_at >= utcnow())
        .limit(1)
    )
    if configured_future_slot is not None:
        return

    psychologists = db.scalars(select(User).where(User.role == "psychologist").order_by(User.nome.asc())).all()
    psychologist_names = [user.nome.strip() for user in psychologists if normalize_optional_text(user.nome)]
    if not psychologist_names:
        return

    valid_names = set(psychologist_names)
    now = utcnow().replace(minute=0, second=0, microsecond=0)

    stale_available_slots = db.scalars(
        select(PsychologistSlot)
        .where(PsychologistSlot.available.is_(True))
        .where(PsychologistSlot.starts_at >= now)
    ).all()
    changed = False
    for slot in stale_available_slots:
        if slot.psychologist_name not in valid_names:
            db.delete(slot)
            changed = True

    if changed:
        db.commit()

    future_slots = db.scalars(
        select(PsychologistSlot)
        .where(PsychologistSlot.starts_at >= now)
        .where(PsychologistSlot.psychologist_name.in_(psychologist_names))
    ).all()
    existing_keys = {(slot.psychologist_name, ensure_utc(slot.starts_at)) for slot in future_slots}
    available_count = sum(1 for slot in future_slots if slot.available)
    if available_count >= 12:
        return

    start_base = now + timedelta(days=1)
    slots: list[PsychologistSlot] = []

    for day_offset in range(0, 6):
        day = start_base + timedelta(days=day_offset)
        for hour in (9, 11, 14, 16):
            slot_start = day.replace(hour=hour)
            slot_end = slot_start + timedelta(minutes=50)
            for psychologist_name in psychologist_names:
                key = (psychologist_name, ensure_utc(slot_start))
                if key in existing_keys:
                    continue
                slots.append(
                    PsychologistSlot(
                        psychologist_name=psychologist_name,
                        starts_at=slot_start,
                        ends_at=slot_end,
                        available=True,
                    )
                )
                existing_keys.add(key)

    db.add_all(slots)
    db.commit()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Mental Health API online"}


@app.post("/auth/register/request-code", response_model=CodeRequestOut)
def request_register_code(data: EmailCodeRequest, db: Session = Depends(get_db)) -> CodeRequestOut:
    normalized_email = normalize_email(data.email)
    existing_user = get_user_by_email(db, normalized_email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email ja cadastrado.")

    code = create_email_verification_code(db, normalized_email, "register")
    if not EMAIL_VERIFICATION_DEBUG:
        send_verification_email(normalized_email, code, "register")
    return CodeRequestOut(
        detail="Codigo de verificacao enviado para o email de cadastro.",
        expires_in_minutes=EMAIL_VERIFICATION_CODE_TTL_MINUTES,
        debug_code=code if EMAIL_VERIFICATION_DEBUG else None,
    )


@app.post("/auth/register", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def register(data: UsuarioCreate, db: Session = Depends(get_db)) -> User:
    if not data.consentimento_lgpd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E necessario aceitar o termo de privacidade para criar a conta.",
        )

    normalized_email = normalize_email(data.email)
    existing_user = get_user_by_email(db, normalized_email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email ja cadastrado.")

    consume_email_verification_code(db, normalized_email, "register", data.codigo)

    role = "admin" if db.scalar(select(User.id).where(User.role == "admin").limit(1)) is None else "user"
    user = User(
        email=normalized_email,
        nome=data.nome.strip(),
        role=role,
        consentimento_lgpd=data.consentimento_lgpd,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login/request-code", response_model=CodeRequestOut)
def request_login_code(data: LoginCodeRequest, db: Session = Depends(get_db)) -> CodeRequestOut:
    normalized_email = normalize_email(data.email)
    user = get_user_by_email(db, normalized_email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email nao encontrado.")
    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou senha invalidos.")

    code = create_email_verification_code(db, normalized_email, "login")
    if not EMAIL_VERIFICATION_DEBUG:
        send_verification_email(normalized_email, code, "login")
    return CodeRequestOut(
        detail="Codigo de verificacao enviado para o email de login.",
        expires_in_minutes=EMAIL_VERIFICATION_CODE_TTL_MINUTES,
        debug_code=code if EMAIL_VERIFICATION_DEBUG else None,
    )


@app.post("/auth/password/request-code", response_model=CodeRequestOut)
def request_password_reset_code(data: PasswordResetCodeRequest, db: Session = Depends(get_db)) -> CodeRequestOut:
    normalized_email = normalize_email(data.email)
    user = get_user_by_email(db, normalized_email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nao existe conta com este email.")

    code = create_email_verification_code(db, normalized_email, "reset")
    if not EMAIL_VERIFICATION_DEBUG:
        send_verification_email(normalized_email, code, "reset")
    return CodeRequestOut(
        detail="Codigo de recuperacao enviado para o email informado.",
        expires_in_minutes=EMAIL_VERIFICATION_CODE_TTL_MINUTES,
        debug_code=code if EMAIL_VERIFICATION_DEBUG else None,
    )


@app.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)) -> Response:
    normalized_email = normalize_email(data.email)
    user = get_user_by_email(db, normalized_email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nao existe conta com este email.")

    consume_email_verification_code(db, normalized_email, "reset", data.codigo)
    user.hashed_password = hash_password(data.nova_senha)
    db.add(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/auth/login", response_model=TokenOut)
def login(data: LoginData, db: Session = Depends(get_db)) -> TokenOut:
    normalized_email = normalize_email(data.email)
    user = get_user_by_email(db, normalized_email)
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou senha invalidos.")

    consume_email_verification_code(db, normalized_email, "login", data.codigo)
    token = create_access_token(user.email)
    return TokenOut(access_token=token)


@app.get("/auth/me", response_model=UsuarioOut)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@app.get("/admin/psychologists", response_model=list[UsuarioOut])
def list_psychologists(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UsuarioOut]:
    psychologists = list(db.scalars(select(User).where(User.role == "psychologist").order_by(User.nome.asc())).all())
    return [build_admin_psychologist_out(item) for item in psychologists]


@app.post("/admin/psychologists", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def create_psychologist(
    data: AdminPsychologistCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UsuarioOut:
    normalized_email = normalize_email(data.email)
    existing_user = get_user_by_email(db, normalized_email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email ja cadastrado.")

    user = User(
        email=normalized_email,
        nome=data.nome.strip(),
        role="psychologist",
        consentimento_lgpd=data.consentimento_lgpd,
        hashed_password=hash_password(data.password),
    )
    set_professional_private_fields(user, normalized_email, data.nome.strip())
    db.add(user)
    db.commit()
    db.refresh(user)
    return build_admin_psychologist_out(user)


@app.patch("/admin/psychologists/{psychologist_id}", response_model=UsuarioOut)
def update_psychologist(
    psychologist_id: str,
    data: AdminPsychologistUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UsuarioOut:
    psychologist = db.get(User, psychologist_id)
    if not psychologist or psychologist.role != "psychologist":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Psicologo nao encontrado.")

    normalized_email = normalize_email(data.email)
    existing_user = get_user_by_email(db, normalized_email)
    if existing_user and existing_user.id != psychologist.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email ja cadastrado.")

    psychologist.email = normalized_email
    psychologist.nome = data.nome.strip()
    set_professional_private_fields(psychologist, normalized_email, data.nome.strip())
    psychologist.consentimento_lgpd = data.consentimento_lgpd
    if data.password:
        psychologist.hashed_password = hash_password(data.password)
    db.add(psychologist)
    db.commit()
    db.refresh(psychologist)
    return build_admin_psychologist_out(psychologist)


@app.delete("/admin/psychologists/{psychologist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_psychologist(
    psychologist_id: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    psychologist = db.get(User, psychologist_id)
    if not psychologist or psychologist.role != "psychologist":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Psicologo nao encontrado.")

    db.delete(psychologist)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.patch("/profile", response_model=UsuarioOut)
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    current_user.nome = data.nome.strip()
    current_user.consentimento_lgpd = data.consentimento_lgpd
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@app.get("/profile/export", response_model=ExportDataOut)
def export_profile_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExportDataOut:
    moods = db.scalars(
        select(MoodEntry).where(MoodEntry.usuario_id == current_user.id).order_by(MoodEntry.criado_em.desc())
    ).all()
    questionnaire_results = db.scalars(
        select(QuestionnaireResult)
        .where(QuestionnaireResult.usuario_id == current_user.id)
        .order_by(QuestionnaireResult.criado_em.desc())
    ).all()
    lia_interactions = list_recent_lia_interactions(db, current_user.id, limit=20)

    return ExportDataOut(
        usuario=current_user,
        humores=moods,
        questionarios=questionnaire_results,
        lia_interacoes=[build_lia_recent_interaction(item) for item in lia_interactions],
        exportado_em=utcnow(),
    )


@app.delete("/profile", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    db.query(MoodEntry).filter(MoodEntry.usuario_id == current_user.id).delete()
    db.query(QuestionnaireResult).filter(QuestionnaireResult.usuario_id == current_user.id).delete()
    db.query(LiaInteraction).filter(LiaInteraction.usuario_id == current_user.id).delete()
    db.query(LiaUserMemory).filter(LiaUserMemory.usuario_id == current_user.id).delete()
    db.query(EmailVerificationCode).filter(EmailVerificationCode.email == current_user.email).delete()
    db.delete(current_user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/moods", response_model=MoodEntryOut, status_code=status.HTTP_201_CREATED)
def create_mood_entry(
    data: MoodEntryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MoodEntry:
    mood = MoodEntry(
        usuario_id=current_user.id,
        valor=data.valor,
        nota=normalize_optional_text(data.nota),
    )
    db.add(mood)
    db.commit()
    db.refresh(mood)
    return mood


@app.get("/moods", response_model=list[MoodEntryOut])
def list_mood_entries(
    limit: int = Query(default=30, ge=1, le=180),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MoodEntry]:
    return db.scalars(
        select(MoodEntry)
        .where(MoodEntry.usuario_id == current_user.id)
        .order_by(MoodEntry.criado_em.desc())
        .limit(limit)
    ).all()


@app.post("/questionnaires/{tipo}", response_model=QuestionnaireResultOut, status_code=status.HTTP_201_CREATED)
def submit_questionnaire(
    tipo: Literal["phq9", "gad7"],
    data: QuestionnaireSubmission,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionnaireResult:
    validate_questionnaire_submission(tipo, data.respostas)
    pontuacao = sum(data.respostas)
    classificacao = classify_score(tipo, pontuacao)

    result = QuestionnaireResult(
        usuario_id=current_user.id,
        tipo=tipo,
        respostas=data.respostas,
        pontuacao=pontuacao,
        classificacao=classificacao,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


@app.get("/questionnaires", response_model=list[QuestionnaireResultOut])
def list_questionnaire_results(
    tipo: Literal["phq9", "gad7"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[QuestionnaireResult]:
    query = select(QuestionnaireResult).where(QuestionnaireResult.usuario_id == current_user.id)
    if tipo:
        query = query.where(QuestionnaireResult.tipo == tipo)
    query = query.order_by(QuestionnaireResult.criado_em.desc()).limit(limit)
    return db.scalars(query).all()


@app.get("/contents", response_model=list[EducationalContentOut])
def list_contents(
    categoria: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[EducationalContent]:
    query = select(EducationalContent).order_by(EducationalContent.titulo.asc())
    if categoria:
        query = query.where(EducationalContent.categoria == categoria)
    return db.scalars(query).all()


@app.post("/lia/start", response_model=LiaTurnOut)
def start_lia_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiaTurnOut:
    memory = get_lia_memory_snapshot(db, current_user)
    session = build_lia_session(memory)
    session.transcript = build_lia_welcome_messages(current_user, memory)
    return LiaTurnOut(session=session, using_ollama=LIA_LLM_ENABLED)


@app.post("/lia/message", response_model=LiaTurnOut)
def lia_message(
    data: LiaTurnInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiaTurnOut:
    if data.session.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta conversa ja foi concluida. Inicie um novo check-in.",
        )

    message_text = normalize_optional_text(data.message)
    if not message_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Envie uma mensagem para a Lia.")

    session = data.session
    session.transcript.append(LiaTranscriptMessage(role="user", content=message_text))
    session.clarification_streak = 0
    session.turn_count += 1
    using_ollama = False
    context = build_lia_context(session, message_text)

    if should_finish_for_triage_handoff(session, context):
        infer_topic_states(session, message_text)
        session.current_topic = "closing"
        session.stage = "closing"
        session.focus_kind = "phq9"
        session.completed = True
        assistant_text = build_triage_handoff_reply(context)
        session.transcript.append(LiaTranscriptMessage(role="assistant", content=assistant_text))
        refresh_dashboard = save_lia_session_results(db, current_user, session)
        return LiaTurnOut(session=session, refresh_dashboard=refresh_dashboard, using_ollama=False)

    scope_guard_reply = build_scope_guard_reply(session, message_text)
    if scope_guard_reply:
        session.transcript.append(LiaTranscriptMessage(role="assistant", content=scope_guard_reply))
        refresh_dashboard = save_lia_session_draft(db, current_user, session)
        return LiaTurnOut(session=session, refresh_dashboard=refresh_dashboard, using_ollama=False)

    infer_topic_states(session, message_text)
    session.current_topic = next_lia_topic(session)

    if session.followup_mode:
        remaining_turns = max(int(session.followup_turns_left or 0) - 1, 0)
        session.followup_turns_left = remaining_turns

        if remaining_turns > 0:
            assistant_text = build_followup_continuation_reply(session, message_text)
            session.transcript.append(LiaTranscriptMessage(role="assistant", content=assistant_text))
            refresh_dashboard = save_lia_session_draft(db, current_user, session)
            return LiaTurnOut(session=session, refresh_dashboard=refresh_dashboard, using_ollama=False)

        assistant_text = build_simple_closing_reply(session, message_text)
        session.stage = "closing"
        session.current_topic = "closing"
        session.focus_kind = "phq9"
        session.completed = True
        session.followup_mode = False
        session.followup_turns_left = 0
        session.followup_finished = True
        session.transcript.append(LiaTranscriptMessage(role="assistant", content=assistant_text))
        refresh_dashboard = save_lia_session_results(db, current_user, session)
        return LiaTurnOut(session=session, refresh_dashboard=refresh_dashboard, using_ollama=False)

    if session.pause_offer_pending:
        session.pause_offer_pending = False
        if is_affirmative_pause_reply(context):
            session.pause_used = True
            assistant_text = build_pause_message(session)
        else:
            assistant_text = build_pause_decline_reply(session)
        session.transcript.append(LiaTranscriptMessage(role="assistant", content=assistant_text))
        refresh_dashboard = save_lia_session_draft(db, current_user, session)
        return LiaTurnOut(session=session, refresh_dashboard=refresh_dashboard, using_ollama=False)

    if should_offer_pause(session, context):
        session.pause_offer_pending = True
        assistant_text = build_pause_offer_reply(session)
        session.transcript.append(LiaTranscriptMessage(role="assistant", content=assistant_text))
        refresh_dashboard = save_lia_session_draft(db, current_user, session)
        return LiaTurnOut(session=session, refresh_dashboard=refresh_dashboard, using_ollama=False)

    try:
        analysis, using_ollama = analyze_lia_turn(session, message_text)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LIA_AI_UNAVAILABLE_DETAIL,
        ) from exc

    session.gad7_scores = merge_scores(session.gad7_scores, analysis.gad7_scores)
    session.phq9_scores = merge_scores(session.phq9_scores, analysis.phq9_scores)

    if analysis.mood_value is not None:
        session.mood_value = analysis.mood_value

    effective_stage = infer_effective_stage(session, analysis, message_text)
    sync_lia_stage(session, analysis)
    gad_answered = count_answered_scores(session.gad7_scores)
    phq_answered = count_answered_scores(session.phq9_scores)
    gad_positive = count_positive_scores(session.gad7_scores)
    phq_positive = count_positive_scores(session.phq9_scores)
    transcript_text = build_memory_source_text(session)
    has_anxiety_context = gad_answered >= 2 or contains_any(
        transcript_text,
        ["ansios", "preocup", "palpit", "coracao", "mente nao desliga", "nao para", "pressao", "medo", "relax"],
    )
    has_mood_context = phq_answered >= 2 or contains_any(
        transcript_text,
        ["sono", "energia", "sem vontade", "automatico", "triste", "vazio", "desanim", "cansad", "nada me anima"],
    )
    enough_distress_data = (
        gad_answered >= 2
        and phq_answered >= 2
        and gad_positive >= 1
        and phq_positive >= 1
    ) or (session.turn_count >= 5 and has_anxiety_context and has_mood_context)
    should_close = should_close_lia_session(session, analysis, effective_stage, enough_distress_data)
    if session.followup_mode:
        current_followup_turns = max(int(session.followup_turns_left or 0) - 1, 0)
        session.followup_turns_left = current_followup_turns
        if current_followup_turns > 0:
            should_close = False
        else:
            should_close = True
    latest_context = build_lia_context(session, message_text)

    if should_close:
        closing_reply: str | None = build_simple_closing_reply(session, message_text)
        if closing_reply:
            analysis.assistant_reply = closing_reply

    if should_close:
        session.stage = "closing"
        session.current_topic = "closing"
        session.focus_kind = "phq9"
        session.completed = True
        session.followup_finished = bool(session.followup_mode)
        session.followup_mode = False
        session.followup_turns_left = 0
    else:
        if session.followup_mode and reply_sounds_like_closing(analysis.assistant_reply):
            analysis.assistant_reply = build_followup_continuation_reply(session, message_text)
        recommended_stage = analysis.recommended_stage
        session.stage = recommended_stage
        if session.stage == "anxiety":
            session.focus_kind = "gad7"
        elif session.stage == "mood":
            session.focus_kind = "phq9"
        else:
            session.focus_kind = None

    assistant_messages: list[str] = []
    refresh_dashboard = False

    if should_close:
        refresh_dashboard = save_lia_session_results(db, current_user, session)
        main_reply = normalize_optional_text(analysis.assistant_reply) or analysis.reflection
        assistant_messages.append(main_reply)
    else:
        primary_reply = normalize_optional_text(analysis.assistant_reply)
        if not primary_reply:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=LIA_AI_UNAVAILABLE_DETAIL,
            )
        assistant_messages.append(primary_reply)

    for item in assistant_messages:
        session.transcript.append(LiaTranscriptMessage(role="assistant", content=item))

    if not should_close:
        refresh_dashboard = save_lia_session_draft(db, current_user, session)

    return LiaTurnOut(
        session=session,
        refresh_dashboard=refresh_dashboard,
        using_ollama=using_ollama,
    )


@app.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardOut:
    lia_memory = get_lia_memory_snapshot(db, current_user)
    dashboard_interactions = list_recent_lia_interactions(db, current_user.id, limit=5, finalized_only=False)
    lia_memory.recent_conversations = [build_lia_recent_interaction(item) for item in dashboard_interactions]
    lia_memory.latest_report = normalize_optional_text(dashboard_interactions[0].report) if dashboard_interactions else None
    triage_request = get_current_triage_request(db, current_user.id)
    moods = db.scalars(
        select(MoodEntry)
        .where(MoodEntry.usuario_id == current_user.id)
        .order_by(MoodEntry.criado_em.desc())
        .limit(14)
    ).all()
    all_results = db.scalars(
        select(QuestionnaireResult)
        .where(QuestionnaireResult.usuario_id == current_user.id)
        .order_by(QuestionnaireResult.criado_em.desc())
        .limit(20)
    ).all()

    latest_mood = moods[0] if moods else None
    latest_phq9 = latest_result_by_type(all_results, "phq9")
    latest_gad7 = latest_result_by_type(all_results, "gad7")
    moods_last_7_days = [mood.valor for mood in moods[:7]]
    average_mood = round(sum(moods_last_7_days) / len(moods_last_7_days), 2) if moods_last_7_days else None

    mood_history = [
        MoodHistoryPoint(data=mood.criado_em.astimezone(timezone.utc).strftime("%d/%m"), valor=mood.valor)
        for mood in reversed(moods)
    ]
    recommendations = build_recommendations(latest_mood, latest_phq9, latest_gad7)
    featured_contents = get_featured_contents(db, latest_mood, latest_phq9, latest_gad7)

    return DashboardOut(
        usuario=current_user,
        estatisticas=DashboardStatOut(
            total_registros_humor=len(moods),
            media_humor_7_dias=average_mood,
            triagens_realizadas=len(all_results),
            ultima_triagem_phq9=latest_phq9.pontuacao if latest_phq9 else None,
            ultima_triagem_gad7=latest_gad7.pontuacao if latest_gad7 else None,
            total_conversas_lia=lia_memory.conversation_count,
        ),
        ultimo_humor=latest_mood,
        ultimos_questionarios=all_results[:6],
        historico_humor=mood_history,
        recomendacoes=recommendations,
        conteudos_em_destaque=featured_contents,
        memoria_lia=lia_memory,
        triagem_atual=build_triage_request_out(triage_request),
    )


@app.get("/triage/slots", response_model=list[TriageSlotOut])
def list_triage_slots(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TriageSlotOut]:
    ensure_triage_slots(db)
    slots = db.scalars(
        select(PsychologistSlot)
        .where(PsychologistSlot.available.is_(True))
        .where(PsychologistSlot.starts_at >= utcnow())
        .order_by(PsychologistSlot.starts_at.asc())
        .limit(12)
    ).all()
    return [
        TriageSlotOut(
            id=slot.id,
            psychologist_name=slot.psychologist_name,
            starts_at=ensure_utc(slot.starts_at),
            ends_at=ensure_utc(slot.ends_at),
            available=bool(slot.available),
        )
        for slot in slots
    ]


@app.get("/psychologist/slots", response_model=list[TriageSlotOut])
def list_my_psychologist_slots(
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> list[TriageSlotOut]:
    if has_role(current_user, "admin"):
        slots = db.scalars(
            select(PsychologistSlot)
            .where(PsychologistSlot.starts_at >= utcnow())
            .order_by(PsychologistSlot.starts_at.asc(), PsychologistSlot.psychologist_name.asc())
            .limit(120)
        ).all()
    else:
        slots = db.scalars(
            select(PsychologistSlot)
            .where(PsychologistSlot.psychologist_name == current_user.nome)
            .where(PsychologistSlot.starts_at >= utcnow())
            .order_by(PsychologistSlot.starts_at.asc())
            .limit(80)
        ).all()

    return [
        TriageSlotOut(
            id=slot.id,
            psychologist_name=slot.psychologist_name,
            starts_at=ensure_utc(slot.starts_at),
            ends_at=ensure_utc(slot.ends_at),
            available=bool(slot.available),
        )
        for slot in slots
    ]


@app.post("/psychologist/slots", response_model=TriageSlotOut, status_code=status.HTTP_201_CREATED)
def create_my_psychologist_slot(
    data: PsychologistSlotCreate,
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> TriageSlotOut:
    if has_role(current_user, "admin") and not has_role(current_user, "psychologist"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas psicologos podem criar horarios.")

    starts_at = ensure_utc(data.starts_at).replace(second=0, microsecond=0)
    ends_at = ensure_utc(data.ends_at).replace(second=0, microsecond=0) if data.ends_at else starts_at + timedelta(minutes=50)
    if starts_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Crie horarios futuros.")
    if ends_at <= starts_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Horario final deve ser depois do inicial.")

    existing = db.scalar(
        select(PsychologistSlot).where(
            PsychologistSlot.psychologist_name == current_user.nome,
            PsychologistSlot.starts_at == starts_at,
        )
    )
    if existing:
        if not existing.available:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este horario ja esta ocupado.")
        existing.ends_at = ends_at
        slot = existing
    else:
        slot = PsychologistSlot(
            psychologist_name=current_user.nome,
            starts_at=starts_at,
            ends_at=ends_at,
            available=True,
        )
        db.add(slot)

    db.commit()
    db.refresh(slot)
    return TriageSlotOut(
        id=slot.id,
        psychologist_name=slot.psychologist_name,
        starts_at=ensure_utc(slot.starts_at),
        ends_at=ensure_utc(slot.ends_at),
        available=bool(slot.available),
    )


@app.delete("/psychologist/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_psychologist_slot(
    slot_id: int,
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> Response:
    slot = db.get(PsychologistSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horario nao encontrado.")
    if not has_role(current_user, "admin") and slot.psychologist_name != current_user.nome:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voce nao pode remover este horario.")
    if not slot.available:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nao e possivel remover horario ja agendado.")

    db.delete(slot)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/triage/request", response_model=TriageRequestOut, status_code=status.HTTP_201_CREATED)
def create_triage_request(
    data: TriageRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TriageRequestOut:
    interaction: LiaInteraction | None = None
    if data.interaction_id:
        interaction = db.get(LiaInteraction, data.interaction_id)
        if interaction is None or interaction.usuario_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interacao nao encontrada.")

    if interaction is None:
        interaction = db.scalar(
            select(LiaInteraction)
            .where(LiaInteraction.usuario_id == current_user.id)
            .order_by(LiaInteraction.created_at.desc())
            .limit(1)
        )

    existing_open_request = db.scalar(
        select(TriageRequest)
        .where(TriageRequest.usuario_id == current_user.id, TriageRequest.status.in_(["pending", "scheduled"]))
        .order_by(TriageRequest.requested_at.desc())
        .limit(1)
    )
    if existing_open_request:
        return build_triage_request_out(existing_open_request)

    request = TriageRequest(
        usuario_id=current_user.id,
        lia_interaction_id=interaction.id if interaction else None,
        status="pending",
        notes="Pedido criado a partir do encerramento com a Lia.",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return build_triage_request_out(request)


@app.post("/triage/schedule", response_model=TriageRequestOut)
def schedule_triage_request(
    data: TriageScheduleInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TriageRequestOut:
    request = db.get(TriageRequest, data.request_id)
    if request is None or request.usuario_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido de triagem nao encontrado.")

    slot = db.get(PsychologistSlot, data.slot_id)
    if slot is None or not slot.available:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Horario indisponivel no momento.")

    slot.available = False
    request.slot_id = slot.id
    request.psychologist_name = slot.psychologist_name
    request.scheduled_for = slot.starts_at
    request.status = "scheduled"
    request.notes = "Triagem agendada a partir de um pedido iniciado com a Lia."
    db.add(slot)
    db.add(request)
    db.commit()
    db.refresh(request)
    return build_triage_request_out(request)


@app.get("/psychologist/triage-requests", response_model=list[PsychologistTriageRequestOut])
def list_psychologist_triage_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> list[PsychologistTriageRequestOut]:
    allowed_statuses = {"pending", "scheduled", "completed", "cancelled"}
    query = (
        select(TriageRequest, User, LiaInteraction)
        .join(User, TriageRequest.usuario_id == User.id)
        .outerjoin(LiaInteraction, TriageRequest.lia_interaction_id == LiaInteraction.id)
        .order_by(
            TriageRequest.scheduled_for.is_(None).asc(),
            TriageRequest.scheduled_for.asc(),
            TriageRequest.requested_at.asc(),
        )
        .limit(80)
    )

    if has_role(current_user, "psychologist") and not has_role(current_user, "admin"):
        query = query.where(
            or_(
                TriageRequest.status == "pending",
                TriageRequest.psychologist_name == current_user.nome,
            )
        )

    if status_filter:
        normalized_status = normalize_optional_text(status_filter)
        if normalized_status not in allowed_statuses:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status de triagem invalido.")
        query = query.where(TriageRequest.status == normalized_status)

    rows = db.execute(query).all()
    return [build_psychologist_triage_request_out(request, user, interaction) for request, user, interaction in rows]


@app.get("/psychologist/triage-requests/{request_id}/patient", response_model=PsychologistPatientDetailOut)
def get_psychologist_patient_detail(
    request_id: str,
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> PsychologistPatientDetailOut:
    request, patient, interaction = get_accessible_triage_row(db, request_id, current_user)

    moods = db.scalars(
        select(MoodEntry)
        .where(MoodEntry.usuario_id == patient.id)
        .order_by(MoodEntry.criado_em.desc())
        .limit(14)
    ).all()
    questionnaires = db.scalars(
        select(QuestionnaireResult)
        .where(QuestionnaireResult.usuario_id == patient.id)
        .order_by(QuestionnaireResult.criado_em.desc())
        .limit(12)
    ).all()
    recent_interactions = list_recent_lia_interactions(db, patient.id, limit=6, finalized_only=False)
    memory = db.get(LiaUserMemory, patient.id)
    lia_memory = build_lia_memory_snapshot(memory, recent_interactions)
    triage_history = db.scalars(
        select(TriageRequest)
        .where(TriageRequest.usuario_id == patient.id)
        .order_by(TriageRequest.requested_at.desc())
        .limit(6)
    ).all()
    note = db.scalar(
        select(PsychologistPatientNote)
        .where(PsychologistPatientNote.request_id == request.id)
        .where(PsychologistPatientNote.psychologist_id == current_user.id)
        .limit(1)
    )

    return PsychologistPatientDetailOut(
        user=patient,
        current_request=build_psychologist_triage_request_out(request, patient, interaction),
        moods=moods,
        questionnaires=questionnaires,
        lia_memory=lia_memory,
        triage_history=[build_triage_request_out(item) for item in triage_history],
        psychologist_note=build_psychologist_note_out(note, request.id, patient.id, current_user.id),
        generated_at=utcnow(),
    )


@app.get(
    "/psychologist/triage-requests/{request_id}/note",
    response_model=PsychologistPatientNoteOut,
)
def get_psychologist_patient_note(
    request_id: str,
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> PsychologistPatientNoteOut:
    request, patient, _ = get_accessible_triage_row(db, request_id, current_user)
    note = db.scalar(
        select(PsychologistPatientNote)
        .where(PsychologistPatientNote.request_id == request.id)
        .where(PsychologistPatientNote.psychologist_id == current_user.id)
        .limit(1)
    )
    return build_psychologist_note_out(note, request.id, patient.id, current_user.id)


@app.patch(
    "/psychologist/triage-requests/{request_id}/note",
    response_model=PsychologistPatientNoteOut,
)
def update_psychologist_patient_note(
    request_id: str,
    data: PsychologistPatientNoteIn,
    current_user: User = Depends(require_psychologist_or_admin),
    db: Session = Depends(get_db),
) -> PsychologistPatientNoteOut:
    request, patient, _ = get_accessible_triage_row(db, request_id, current_user)
    note = db.scalar(
        select(PsychologistPatientNote)
        .where(PsychologistPatientNote.request_id == request.id)
        .where(PsychologistPatientNote.psychologist_id == current_user.id)
        .limit(1)
    )

    if note is None:
        note = PsychologistPatientNote(
            request_id=request.id,
            patient_id=patient.id,
            psychologist_id=current_user.id,
            content=data.content.strip(),
        )
    else:
        note.content = data.content.strip()
        note.updated_at = utcnow()

    db.add(note)
    db.commit()
    db.refresh(note)
    return build_psychologist_note_out(note, request.id, patient.id, current_user.id)


