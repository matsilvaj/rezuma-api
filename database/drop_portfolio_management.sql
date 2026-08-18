-- =============================================================================
-- Drop: gestão de carteira de investimentos (migration 007)
-- Execute no SQL Editor do Supabase
-- =============================================================================

-- Tabelas com dependências primeiro
drop table if exists public.portfolio_long_term_goals cascade;
drop table if exists public.darf_monthly cascade;
drop table if exists public.fixed_income_investments cascade;
drop table if exists public.asset_prices cascade;
drop table if exists public.portfolio_positions cascade;
drop table if exists public.portfolio_transactions cascade;
drop table if exists public.brokerage_notes cascade;
drop table if exists public.portfolio_strategies cascade;

-- Colunas adicionadas em tabelas existentes
alter table public.assets
    drop column if exists strategy_id,
    drop column if exists target_pct;

alter table public.user_profiles
    drop column if exists monthly_income_target;
