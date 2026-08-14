# Alerta Diário Oficial de Santos

Monitora diariamente a edição do [Diário Oficial de Santos](https://diariooficial.santos.sp.gov.br/)
e avisa por e-mail (com o PDF anexado) quando um nome completo ou palavra-chave
cadastrado por algum usuário aparece na publicação. O administrador recebe
cópia de todo match e de todo novo cadastro.

**Status:** MVP com um único canal (e-mail). SMS/WhatsApp ficam previstos no
schema (`users.canais`) mas não implementados ainda — ver "Próximos passos".

## Como funciona

- `db/schema.sql` — tabelas `users`, `search_terms`, `matches` no Postgres do
  Supabase, com RLS para que cada pessoa só veja/edite os próprios dados.
- `docs/index.html` — página estática de cadastro e autoatendimento. Login por
  magic link (Supabase Auth) — sem senha, e o clique no link já serve como
  confirmação de e-mail.
- `scraper/robo_diario.py` — script Python que baixa a edição do dia, extrai
  o texto (o PDF já vem com camada de texto pesquisável, não precisa de OCR),
  compara com os termos ativos e envia e-mail via Resend.
- `.github/workflows/diario.yml` — roda o robô todo dia útil via GitHub
  Actions (cron), sem precisar de servidor próprio.
- `supabase/functions/notify-signup/` — Edge Function opcional que avisa o
  admin por e-mail a cada novo cadastro (disparada por um Database Webhook).

## Contas necessárias

1. **Supabase** (https://supabase.com) — banco de dados + autenticação. Plano
   gratuito é suficiente para começar.
2. **Resend** (https://resend.com) — envio de e-mail transacional. Plano
   gratuito cobre uso baixo/moderado. Precisa verificar um domínio (ou usar o
   domínio de teste deles enquanto valida o projeto).
3. **GitHub** — repositório para hospedar o código e rodar o cron via Actions
   (gratuito para repositórios públicos ou com o limite do plano free).
4. Hospedagem da página `docs/index.html`: qualquer estático serve (GitHub
   Pages, Netlify, Vercel). Não precisa de backend próprio — ela fala direto
   com o Supabase.

## Setup passo a passo

### 1. Supabase
1. Crie um projeto novo em supabase.com.
2. Vá em **SQL Editor**, cole o conteúdo de `db/schema.sql` e rode.
3. Em **Authentication > Providers**, confirme que "Email" está habilitado
   com "Magic Link" (é o padrão).
4. Em **Authentication > URL Configuration**, adicione a URL onde a
   `docs/index.html` vai ficar hospedada (ex.: `https://seu-usuario.github.io/alerta-diario/`)
   em "Redirect URLs".
5. Em **Project Settings > API**, copie a `Project URL`, a `anon public key`
   e a `service_role key` (esta última é secreta — nunca vai no frontend).

### 2. Página de cadastro (`docs/index.html`)
1. Edite as constantes `SUPABASE_URL` e `SUPABASE_ANON_KEY` no topo do
   `<script>` com os valores do passo anterior.
2. Publique o arquivo em qualquer hospedagem estática.
3. Cadastre-se você mesmo pela página (recebe o magic link, entra, preenche
   nome).
4. Volte ao **SQL Editor** do Supabase e rode:
   ```sql
   update users set is_admin = true where email = 'seu-email@exemplo.com';
   ```

### 3. Resend (e-mail)
1. Crie conta, verifique um domínio (ou use o domínio de teste deles para
   validar antes de ir a público).
2. Gere uma API key.

### 4. Robô diário (GitHub Actions)
1. Suba esta pasta como repositório no GitHub.
2. Em **Settings > Secrets and variables > Actions**, adicione:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY` (a `service_role key`, não a anon)
   - `RESEND_API_KEY`
   - `EMAIL_REMETENTE` (ex.: `Alerta DO Santos <alertas@seudominio.com>`,
     precisa ser um endereço do domínio verificado no Resend)
3. O workflow `.github/workflows/diario.yml` já roda de segunda a sexta às
   09:30 (horário de Brasília). Ajuste o `cron:` se necessário, ou dispare
   manualmente pela aba **Actions > Alerta Diário Oficial de Santos > Run
   workflow** (aceita uma data específica para testar contra uma edição
   antiga).

Testar localmente antes de confiar no cron:
```bash
cd scraper
pip install -r requirements.txt
export SUPABASE_URL=...
export SUPABASE_SERVICE_KEY=...
export RESEND_API_KEY=...
export EMAIL_REMETENTE="Alerta DO Santos <alertas@seudominio.com>"
python robo_diario.py --data 2026-08-14
```

### 5. Notificação de novo cadastro para o admin (opcional, mas recomendado)
1. Instale a Supabase CLI e rode `supabase login` / `supabase link`.
2. `supabase secrets set RESEND_API_KEY=... EMAIL_REMETENTE=... SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...`
3. `supabase functions deploy notify-signup`
4. No painel: **Database > Webhooks > Create a new hook** — tabela `users`,
   evento `INSERT`, tipo `HTTP Request` apontando para a URL da function
   deployada.

## Limitações conhecidas do MVP

- Só e-mail. SMS e WhatsApp não estão implementados (o campo `canais` no
  banco já está preparado para isso).
- O Diário costuma não publicar aos fins de semana/feriados — o robô trata
  um 404 nesses dias como "sem edição" e simplesmente não faz nada (ver
  `baixa_edicao` em `robo_diario.py`).
- Se o layout do PDF mudar (ex.: passar a ser digitalizado/escaneado), a
  extração de texto do `pdfplumber` para de funcionar e seria necessário
  adicionar OCR (`pytesseract`) como fallback.

## Próximos passos sugeridos

- WhatsApp via Meta Cloud API ou Twilio (ver conversa de planejamento).
- SMS via Twilio/Zenvia — como SMS não aceita anexo, mandar link de
  download em vez do PDF.
- Página de política de privacidade / LGPD linkada no cadastro.
