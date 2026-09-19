-- =============================================================================
-- 007: encerra o trial no cadastro
--
-- Decisão de produto: o Rezuma não tem período gratuito. Quem entra assina, e
-- a garantia de reembolso em 30 dias é o que tira o risco de quem hesita.
--
-- O banco criava toda assinatura com trial_ends_at = now() + 7 dias, e nada
-- no sistema comparava essa data com o presente: o status continuava
-- 'trialing' indefinidamente e o portão do agendador deixava todo mundo
-- passar. Agora quem decide é app/core/subscription.py, que exige status
-- 'active' ou uma janela de trial ainda aberta.
--
-- Nascendo com trial_ends_at = now(), a janela nasce fechada. Voltar a
-- oferecer trial é mudar este default (ex.: now() + interval '3 days'),
-- sem tocar em código.
-- =============================================================================

alter table public.subscriptions
    alter column trial_ends_at set default now();


-- Contas que já existem seguem com a janela aberta até a data original.
-- Para fechar o trial de quem se cadastrou antes desta migração e nunca
-- pagou, rode também:
--
--   update public.subscriptions
--      set trial_ends_at = now()
--    where status = 'trialing'
--      and trial_ends_at > now();
--
-- Deixado comentado de propósito: fecha o acesso de todo mundo que está
-- testando agora, inclusive as suas próprias contas de teste.
