# Deploy gratuito para teste da Lia

Este guia deixa o app acessivel para a orientadora testar fora do computador local, usando planos gratuitos.

## Arquitetura recomendada

- Frontend: Vercel Hobby
- Backend: Render Free Web Service
- Banco: Supabase Free PostgreSQL
- Email de codigos: Resend Free

Observacoes importantes:

- Render Free pode "dormir" apos alguns minutos sem acesso. O primeiro carregamento pode demorar perto de 1 minuto.
- Nao use SQLite em deploy gratuito do Render: o filesystem e temporario e pode perder dados. Use PostgreSQL.
- Para teste de TCC, nao cadastre dados reais sensiveis sem consentimento claro. Use pacientes ficticios sempre que possivel.

## 1. Banco gratuito no Supabase

1. Crie um projeto no Supabase.
2. Copie a connection string PostgreSQL.
3. Use a URL no formato aceito pelo SQLAlchemy:

```text
postgresql://USUARIO:SENHA@HOST:PORTA/BANCO
```

Essa URL sera usada como `DATABASE_URL` no Render.

## 2. Backend no Render

1. Conecte o GitHub no Render.
2. Crie um Web Service usando este repositorio.
3. Se usar Blueprint, o arquivo `render.yaml` ja define build e start.
4. Configure as variaveis:

```text
ENVIRONMENT=production
DATABASE_URL=postgresql://...
FRONTEND_ORIGINS=https://SEU-FRONTEND.vercel.app
ADMIN_EMAILS=seu-email-admin@gmail.com
DATA_ENCRYPTION_KEY=gere-com-fernet
OLLAMA_ENABLED=false
EMAIL_VERIFICATION_DEBUG=false
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=onboarding@resend.dev
RESEND_FROM_NAME=Lia
```

Gere `DATA_ENCRYPTION_KEY` localmente com:

```powershell
cd C:\mental-health-app\backend
.\.venv_clean\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

O `SECRET_KEY` pode ser gerado automaticamente pelo Render se voce usar o Blueprint. Se criar manualmente, gere uma chave forte e longa.

## 3. Frontend no Vercel

1. Importe o repositorio no Vercel.
2. Configure:

```text
Root Directory: frontend
Build Command: npm run build
Output Directory: dist
```

3. Configure a variavel:

```text
VITE_API_URL=https://SEU-BACKEND.onrender.com
```

4. Depois de publicar, volte ao Render e atualize `FRONTEND_ORIGINS` com a URL final do Vercel.

## 4. Primeiro login ADM

Use seu email em `ADMIN_EMAILS`.

Fluxo recomendado:

1. Abra o frontend publicado.
2. Cadastre sua conta com o email definido em `ADMIN_EMAILS`.
3. Ao logar, o backend reconhece esse email como `admin`.
4. No painel ADM, crie os logins dos psicologos.

## 5. Logins iniciais sugeridos

- ADM: seu email pessoal definido em `ADMIN_EMAILS`.
- Psicologa orientadora: criar pelo painel ADM.
- Pacientes: criar pelo cadastro normal ou deixar a orientadora criar pacientes ficticios.

## 6. Checklist de seguranca minima

- `ENVIRONMENT=production`
- `SECRET_KEY` forte e fora do Git
- `DATA_ENCRYPTION_KEY` gerada e fora do Git
- `EMAIL_VERIFICATION_DEBUG=false`
- `FRONTEND_ORIGINS` com apenas a URL do Vercel
- `DATABASE_URL` apontando para PostgreSQL, nao SQLite
- Nao subir `.env`, `.db`, logs ou pacientes reais para o Git

