from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


load_local_env_file()


def env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower() or "development"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mental_health.db")
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if ENVIRONMENT == "development":
        SECRET_KEY = "development-only-secret-key-change-me"
    else:
        raise RuntimeError("SECRET_KEY must be configured outside development.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
EMAIL_VERIFICATION_CODE_TTL_MINUTES = int(os.getenv("EMAIL_VERIFICATION_CODE_TTL_MINUTES", "10"))
EMAIL_VERIFICATION_DEBUG = env_flag("EMAIL_VERIFICATION_DEBUG", False)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME).strip()
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Mental Health App").strip() or "Mental Health App"
SMTP_USE_TLS = env_flag("SMTP_USE_TLS", True)
SMTP_USE_SSL = env_flag("SMTP_USE_SSL", False)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_API_URL = os.getenv("RESEND_API_URL", "https://api.resend.com/emails").strip()
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "").strip()
RESEND_FROM_NAME = os.getenv("RESEND_FROM_NAME", "Mental Health App").strip() or "Mental Health App"
LIA_AI_UNAVAILABLE_DETAIL = (
    "A Lia precisa do Ollama ativo para responder agora. Inicie o Ollama e tente novamente."
)

QUESTIONNAIRE_CONFIG = {
    "phq9": {
        "title": "PHQ-9",
        "question_count": 9,
        "severity": [
            (0, 4, "Sintomas minimos"),
            (5, 9, "Sintomas leves"),
            (10, 14, "Sintomas moderados"),
            (15, 19, "Sintomas moderadamente graves"),
            (20, 27, "Sintomas graves"),
        ],
    },
    "gad7": {
        "title": "GAD-7",
        "question_count": 7,
        "severity": [
            (0, 4, "Ansiedade minima"),
            (5, 9, "Ansiedade leve"),
            (10, 14, "Ansiedade moderada"),
            (15, 21, "Ansiedade grave"),
        ],
    },
}

SEEDED_CONTENTS = [
    {
        "slug": "rotina-de-autocuidado",
        "titulo": "Rotina curta de autocuidado",
        "categoria": "Autocuidado",
        "resumo": "Passos simples para organizar sono, alimentacao, movimento e pausas ao longo do dia.",
        "conteudo": (
            "Monte uma rotina minima de autocuidado com horarios razoaveis para dormir, pequenas pausas "
            "durante o dia, hidratacao e uma atividade fisica leve. Mudancas pequenas e consistentes "
            "costumam ser mais sustentaveis do que metas muito ambiciosas."
        ),
        "nivel": "geral",
        "questionario_tipo": None,
    },
    {
        "slug": "respiracao-4-6",
        "titulo": "Tecnica de respiracao 4-6",
        "categoria": "Ansiedade",
        "resumo": "Uma estrategia rapida para desacelerar quando o corpo estiver muito ativado.",
        "conteudo": (
            "Inspire pelo nariz contando quatro segundos e solte o ar lentamente por seis segundos. "
            "Repita por dois a cinco minutos e observe a diminuicao gradual da tensao corporal."
        ),
        "nivel": "leve",
        "questionario_tipo": "gad7",
    },
    {
        "slug": "registro-de-pensamentos",
        "titulo": "Registro de pensamentos automaticos",
        "categoria": "Reestruturacao cognitiva",
        "resumo": "Estruture uma situacao, o pensamento associado e uma resposta mais equilibrada.",
        "conteudo": (
            "Quando perceber uma emocao intensa, descreva a situacao, identifique o pensamento automatico "
            "que surgiu e tente formular uma interpretacao alternativa mais realista e gentil."
        ),
        "nivel": "moderado",
        "questionario_tipo": "phq9",
    },
    {
        "slug": "sinais-de-alerta",
        "titulo": "Quando buscar ajuda profissional",
        "categoria": "Orientacao",
        "resumo": "Sinais de alerta que indicam a importancia de procurar psicologo, psiquiatra ou CAPS.",
        "conteudo": (
            "Procure apoio profissional quando os sintomas estiverem frequentes, afetarem estudo, trabalho, "
            "sono, relacionamento ou funcionamento diario. Em situacoes de crise ou risco imediato, busque "
            "ajuda emergencial local imediatamente."
        ),
        "nivel": "alto",
        "questionario_tipo": None,
    },
    {
        "slug": "higiene-do-sono",
        "titulo": "Boas praticas de higiene do sono",
        "categoria": "Sono",
        "resumo": "Ajustes ambientais e comportamentais para melhorar regularidade e qualidade do sono.",
        "conteudo": (
            "Evite telas antes de dormir, reduza cafeina no fim do dia, mantenha horario regular e deixe o "
            "ambiente escuro e silencioso. O sono influencia diretamente humor, energia e ansiedade."
        ),
        "nivel": "geral",
        "questionario_tipo": None,
    },
    {
        "slug": "micro-pausas",
        "titulo": "Micro pausas para regular o dia",
        "categoria": "Bem-estar",
        "resumo": "Pequenas pausas intencionais ajudam a reduzir sobrecarga mental e fisica.",
        "conteudo": (
            "A cada bloco de trabalho ou estudo, faca uma pausa breve para alongar, respirar e sair do modo "
            "automatico. Esse intervalo curto ajuda a reduzir fadiga cognitiva e irritabilidade."
        ),
        "nivel": "geral",
        "questionario_tipo": None,
    },
]
