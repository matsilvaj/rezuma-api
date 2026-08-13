-- Migration 002: cria catálogo de ativos da B3 e adiciona FK em assets
-- Execute no SQL Editor do Supabase

-- Catálogo de todos os ativos negociados na B3 (ações e FIIs)
create table public.b3_assets (
    ticker      text        primary key,
    name        text        not null,
    type        text        not null, -- acao | fii
    updated_at  timestamptz not null default now()
);

-- Leitura pública para qualquer usuário autenticado (necessário para o autocomplete)
alter table public.b3_assets enable row level security;

create policy "b3_assets: authenticated read"
    on public.b3_assets for select
    to authenticated
    using (true);

-- Impede cadastro de ticker que não existe no catálogo da B3
alter table public.assets
    add constraint fk_assets_ticker
    foreign key (ticker) references public.b3_assets(ticker);
