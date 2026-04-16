# Mental Health App

Aplicativo web de apoio a saude mental.

## O que esta implementado

- Cadastro e login com JWT
- Consentimento LGPD no cadastro e no perfil
- Edicao de perfil com dados essenciais da conta
- Exportacao e exclusao de dados do usuario
- Registro de humor com persistencia em banco
- Aplicacao dos questionarios PHQ-9 e GAD-7
- Historico de respostas e classificacao automatica
- Dashboard com metricas, grafico simples e recomendacoes automaticas
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

## Como rodar

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Frontend em `http://localhost:5173`
Backend em `http://localhost:8000`

## Rotas principais do app

- `/dashboard`
- `/humor`
- `/phq9`
- `/gad7`
- `/contents`
- `/profile`

## Observacao

O sistema foi organizado para oferecer autenticacao, triagem, acompanhamento e conteudo educativo em um unico fluxo.


