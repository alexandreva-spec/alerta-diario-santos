-- Schema para o alerta de Diário Oficial de Santos
-- Rodar no SQL editor de um projeto Supabase novo.
--
-- Autenticação/autoatendimento: usamos o Supabase Auth (magic link) em vez de
-- reinventar confirmação de e-mail por token. `users.id` é o mesmo id de
-- `auth.users` — ou seja, a pessoa só existe em `public.users` depois de
-- clicar no link mágico recebido por e-mail, o que já resolve o double opt-in.
--
-- Canais de notificação: o campo `canais` já suporta email/sms/whatsapp,
-- mas o MVP só implementa 'email' — os outros ficam reservados para depois.

create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  nome text not null,
  email text not null unique,
  telefone text,
  canais text[] not null default array['email'],
  is_admin boolean not null default false,
  ativo boolean not null default true,
  created_at timestamptz not null default now()
);

create table search_terms (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  tipo text not null check (tipo in ('nome_completo', 'palavra_chave')),
  valor text not null,
  ativo boolean not null default true,
  created_at timestamptz not null default now()
);

create table matches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  search_term_id uuid not null references search_terms(id) on delete cascade,
  data_edicao date not null,
  pagina int,
  trecho text,
  notificado_em timestamptz,
  created_at timestamptz not null default now(),
  unique (search_term_id, data_edicao)
);

create index idx_search_terms_user on search_terms(user_id);
create index idx_search_terms_ativo on search_terms(ativo) where ativo;
create index idx_matches_user on matches(user_id);
create index idx_matches_data on matches(data_edicao);

-- Row Level Security: cada pessoa só enxerga/edita os próprios dados.
-- O robô diário e a função de notificação de admin usam a service_role key,
-- que ignora RLS por padrão — então essas policies só valem para a página
-- de autoatendimento (que usa a anon key + sessão do usuário logado).

alter table users enable row level security;
alter table search_terms enable row level security;
alter table matches enable row level security;

create policy "usuario le o proprio perfil"
  on users for select
  using (auth.uid() = id);

create policy "usuario cria o proprio perfil"
  on users for insert
  with check (auth.uid() = id);

create policy "usuario edita o proprio perfil"
  on users for update
  using (auth.uid() = id);

create policy "usuario le os proprios termos"
  on search_terms for select
  using (auth.uid() = user_id);

create policy "usuario cria os proprios termos"
  on search_terms for insert
  with check (auth.uid() = user_id);

create policy "usuario edita os proprios termos"
  on search_terms for update
  using (auth.uid() = user_id);

create policy "usuario apaga os proprios termos"
  on search_terms for delete
  using (auth.uid() = user_id);

create policy "usuario le os proprios matches"
  on matches for select
  using (auth.uid() = user_id);

-- Depois do seu próprio cadastro pela página web, rode manualmente no SQL
-- editor para virar admin (troque o e-mail):
-- update users set is_admin = true where email = 'seu-email@exemplo.com';

-- Database Webhook (Database > Webhooks no painel Supabase):
-- evento INSERT na tabela `users` -> chama a Edge Function `notify-signup`
-- (ver supabase/functions/notify-signup) para te avisar por e-mail de novos
-- cadastros.
