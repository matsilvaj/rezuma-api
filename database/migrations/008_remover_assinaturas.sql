-- =============================================================================
-- 008: remove assinaturas
--
-- O Rezuma passou a ser gratuito, mantido por doação via Pix. Não há mais
-- cobrança, trial nem Stripe, então a tabela de assinaturas perde a razão de
-- existir. Substitui a 007, que só ajustava o trial desta mesma tabela.
--
-- A ordem é obrigatória: o trigger de cadastro insere em subscriptions. Se a
-- tabela sumir antes da função ser trocada, todo cadastro novo falha dentro
-- do Supabase Auth com um erro que não aponta para cá.
-- =============================================================================

-- 1. Cadastro deixa de criar assinatura
create or replace function public.handle_new_user()
returns trigger as $$
begin
    insert into public.user_profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name');

    return new;
end;
$$ language plpgsql security definer;

-- 2. Só então a tabela sai. O cascade leva junto o trigger de updated_at e a
--    policy de RLS, que pertencem a ela.
drop table if exists public.subscriptions cascade;
