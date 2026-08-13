-- Adiciona coluna de métricas extraídas pela IA por relatório.
-- Usado para comparação mês a mês (ex: DY, vacância, receita).
alter table public.reports
    add column if not exists metrics jsonb;
