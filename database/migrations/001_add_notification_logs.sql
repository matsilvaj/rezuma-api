-- Migration 001: adiciona tabela de logs de notificação
-- Execute no SQL Editor do Supabase caso o schema.sql inicial já tenha sido aplicado

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

alter table public.notification_logs enable row level security;

create policy "notification_logs: select own"
    on public.notification_logs for select
    using (auth.uid() = user_id);

create index idx_notification_logs_user_report
    on public.notification_logs(user_id, report_id);
