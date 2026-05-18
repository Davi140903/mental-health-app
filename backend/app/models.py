from __future__ import annotations

from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase

from .db import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    nome = Column(String, nullable=False)
    professional_email_encrypted = Column(Text, nullable=True)
    professional_name_encrypted = Column(Text, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user", index=True)
    consentimento_lgpd = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    email = Column(String, nullable=False, index=True)
    purpose = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class MoodEntry(Base):
    __tablename__ = "mood_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    usuario_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    valor = Column(Integer, nullable=False)
    nota = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class QuestionnaireResult(Base):
    __tablename__ = "questionnaire_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    usuario_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    tipo = Column(String, nullable=False, index=True)
    respostas = Column(JSON, nullable=False)
    pontuacao = Column(Integer, nullable=False)
    classificacao = Column(String, nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class EducationalContent(Base):
    __tablename__ = "educational_contents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    titulo = Column(String, nullable=False)
    categoria = Column(String, nullable=False)
    resumo = Column(Text, nullable=False)
    conteudo = Column(Text, nullable=False)
    nivel = Column(String, nullable=False, default="geral")
    questionario_tipo = Column(String, nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class LiaUserMemory(Base):
    __tablename__ = "lia_user_memories"

    usuario_id = Column(String, ForeignKey("users.id"), primary_key=True)
    resumo = Column(Text, nullable=True)
    resumo_recente = Column(Text, nullable=True)
    topicos = Column(JSON, nullable=False, default=list)
    total_conversas = Column(Integer, nullable=False, default=0)
    ultimo_humor_valor = Column(Integer, nullable=True)
    primeiro_contato_concluido = Column(Boolean, nullable=False, default=False)
    criado_em = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    atualizado_em = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class LiaInteraction(Base):
    __tablename__ = "lia_interactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    usuario_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    session_key = Column(String, nullable=True, index=True)
    opening_label = Column(String, nullable=True)
    opening_value = Column(String, nullable=True)
    summary = Column(Text, nullable=False)
    report = Column(Text, nullable=True)
    transcript = Column(JSON, nullable=False, default=list)
    topics = Column(JSON, nullable=False, default=list)
    mood_value = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="final", index=True)
    finalized = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class PsychologistSlot(Base):
    __tablename__ = "psychologist_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    psychologist_name = Column(String, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    available = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class TriageRequest(Base):
    __tablename__ = "triage_requests"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    usuario_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    lia_interaction_id = Column(String, ForeignKey("lia_interactions.id"), nullable=True, index=True)
    slot_id = Column(Integer, ForeignKey("psychologist_slots.id"), nullable=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    psychologist_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True, index=True)


class PsychologistPatientNote(Base):
    __tablename__ = "psychologist_patient_notes"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    request_id = Column(String, ForeignKey("triage_requests.id"), nullable=False, index=True)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    psychologist_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
