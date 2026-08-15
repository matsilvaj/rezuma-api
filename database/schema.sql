-- =============================================================================
-- Rezuma — Schema do banco de dados
-- Execute no SQL Editor do Supabase na ordem em que está escrito
-- =============================================================================


-- =============================================================================
-- EXTENSÕES
-- =============================================================================

create extension if not exists "uuid-ossp";


-- =============================================================================
-- TABELAS
-- =============================================================================

-- Perfil público do usuário, vinculado ao auth.users do Supabase
create table public.user_profiles (
    id              uuid        primary key references auth.users(id) on delete cascade,
    full_name       text,
    telegram_chat_id text       unique,
    notify_email    boolean     not null default true,
    notify_telegram boolean     not null default false,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Ativos cadastrados na carteira de cada usuário
create table public.assets (
    id          uuid        primary key default uuid_generate_v4(),
    user_id     uuid        not null references auth.users(id) on delete cascade,
    ticker      text        not null,
    created_at  timestamptz not null default now(),

    -- Impede que o mesmo ativo seja cadastrado duas vezes pelo mesmo usuário
    unique(user_id, ticker)
);

-- Relatórios processados pela IA, independentes de usuário
create table public.reports (
    id              uuid        primary key default uuid_generate_v4(),
    ticker          text        not null,
    title           text        not null,
    summary         text        not null,
    source_url      text        not null,
    document_type   text        not null, -- informe_mensal | fato_relevante | ITR | DFP
    published_at    timestamptz not null,
    created_at      timestamptz not null default now(),

    -- Impede reprocessamento do mesmo documento
    unique(ticker, source_url)
);

-- Registro de notificações enviadas por usuário e relatório
-- Evita reenvio do mesmo relatório pelo mesmo canal
create table public.notification_logs (
    id          uuid        primary key default uuid_generate_v4(),
    user_id     uuid        not null references auth.users(id) on delete cascade,
    report_id   uuid        not null references public.reports(id) on delete cascade,
    channel     text        not null, -- email | telegram
    status      text        not null, -- sent | failed
    sent_at     timestamptz not null default now(),

    -- Garante que o mesmo relatório não seja enviado duas vezes pelo mesmo canal
    unique(user_id, report_id, channel)
);

-- Dados de assinatura de cada usuário (gerenciados via Stripe)
create table public.subscriptions (
    id                      uuid        primary key default uuid_generate_v4(),
    user_id                 uuid        not null unique references auth.users(id) on delete cascade,
    stripe_customer_id      text        unique,
    stripe_subscription_id  text        unique,
    status                  text        not null default 'trialing', -- trialing | active | past_due | canceled
    plan                    text,                                     -- monthly | annual
    trial_ends_at           timestamptz not null default (now() + interval '7 days'),
    current_period_end      timestamptz,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);


-- =============================================================================
-- TRIGGER: updated_at automático
-- Atualiza o campo updated_at sempre que uma linha for modificada
-- =============================================================================

create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger trg_user_profiles_updated_at
    before update on public.user_profiles
    for each row execute function public.set_updated_at();

create trigger trg_subscriptions_updated_at
    before update on public.subscriptions
    for each row execute function public.set_updated_at();


-- =============================================================================
-- TRIGGER: novo usuário
-- Cria automaticamente perfil e assinatura (trial 7 dias) ao registrar
-- =============================================================================

create or replace function public.handle_new_user()
returns trigger as $$
begin
    -- Cria perfil público vinculado ao auth.users, capturando o nome do metadata
    insert into public.user_profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name');

    -- Inicia trial de 7 dias automaticamente
    insert into public.subscriptions (user_id)
    values (new.id);

    return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();


-- =============================================================================
-- ROW LEVEL SECURITY (RLS)
-- Garante que cada usuário acessa apenas os próprios dados
-- O backend usa service_role_key e bypassa o RLS
-- =============================================================================

alter table public.user_profiles      enable row level security;
alter table public.assets              enable row level security;
alter table public.reports             enable row level security;
alter table public.notification_logs   enable row level security;
alter table public.subscriptions       enable row level security;


-- user_profiles: usuário acessa apenas o próprio perfil
create policy "user_profiles: select own"
    on public.user_profiles for select
    using (auth.uid() = id);

create policy "user_profiles: update own"
    on public.user_profiles for update
    using (auth.uid() = id);


-- assets: usuário acessa apenas os próprios ativos
create policy "assets: select own"
    on public.assets for select
    using (auth.uid() = user_id);

create policy "assets: insert own"
    on public.assets for insert
    with check (auth.uid() = user_id);

create policy "assets: delete own"
    on public.assets for delete
    using (auth.uid() = user_id);


-- reports: usuário vê apenas relatórios dos tickers que possui na carteira
create policy "reports: select by owned tickers"
    on public.reports for select
    using (
        exists (
            select 1 from public.assets
            where assets.user_id = auth.uid()
              and assets.ticker   = reports.ticker
        )
    );


-- notification_logs: usuário vê apenas as próprias notificações
create policy "notification_logs: select own"
    on public.notification_logs for select
    using (auth.uid() = user_id);


-- subscriptions: usuário acessa apenas a própria assinatura
create policy "subscriptions: select own"
    on public.subscriptions for select
    using (auth.uid() = user_id);


-- =============================================================================
-- ÍNDICES
-- Melhoram performance nas consultas mais frequentes
-- =============================================================================

-- Busca de ativos por usuário
create index idx_assets_user_id on public.assets(user_id);

-- Busca de relatórios por ticker
create index idx_reports_ticker on public.reports(ticker);

-- Busca de relatórios por data de publicação (feed cronológico)
create index idx_reports_published_at on public.reports(published_at desc);

-- Busca de logs por usuário (verificar se já foi notificado)
create index idx_notification_logs_user_report on public.notification_logs(user_id, report_id);
