# Mental Health App

Aplicativo web de apoio a saude mental.

## O que esta implementado

- Cadastro e login com JWT
- Verificacao por codigo no cadastro e no login
- Consentimento LGPD no cadastro e no perfil
- Edicao de perfil com dados essenciais da conta
- Exportacao e exclusao de dados do usuario
- Registro de humor com persistencia em banco
- Aplicacao dos questionarios PHQ-9 e GAD-7
- Historico de respostas e classificacao automatica
- Dashboard com metricas, grafico simples e recomendacoes automaticas
- Espaco conversacional da Lia com memoria resumida
- Biblioteca inicial de conteudos educativos

## Stack

### Frontend
- React
- TypeScript
- Vite
- React Router
- Axios

### Backend
- FastAPI
- SQLAlchemy
- SQLite
- JWT
- Bcrypt

## Estrutura

- `frontend/`: interface web
- `backend/`: API e banco local SQLite
- `backend/app/`: configuracao, banco, modelos e schemas compartilhados

## Como rodar

### Frontend
```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload
```

Frontend em `http://localhost:5173`
Backend em `http://localhost:8000`

## Configuracao importante

- Defina `SECRET_KEY` no `backend/.env`. Em producao ela e obrigatoria.
- Se quiser usar a Lia com IA local, deixe o Ollama rodando em `http://127.0.0.1:11434`.
- Em ambiente local, `EMAIL_VERIFICATION_DEBUG=true` preenche o codigo na interface sem depender de email real.

## Rotas principais do app

- `/dashboard`
- `/lia`
- `/humor`
- `/phq9`
- `/gad7`
- `/contents`
- `/profile`

## Observacao

O sistema foi organizado para oferecer autenticacao, triagem, acompanhamento e conteudo educativo em um unico fluxo. A visao geral fica em `/dashboard`, enquanto a conversa principal com a Lia fica em `/lia`.


