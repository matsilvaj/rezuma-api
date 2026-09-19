-- =============================================================================
-- 009: fecha a escrita direta pelo Supabase
--
-- A chave anon fica no bundle do front, qualquer um lê no navegador. Com ela
-- e o próprio login, dá para chamar a REST do Supabase direto, sem passar pela
-- API. As policies abaixo permitiam exatamente isso:
--
--   assets: insert own     contornava o limite de 30 ativos, que só existia
--                          na API. O agendador processa toda linha de assets,
--                          então cada ticker inserido assim virava custo de IA.
--   user_profiles: update  permitia gravar qualquer coluna, inclusive
--                          telegram_chat_id, que a API bloqueia de propósito:
--                          dava para apontar notificações para o chat de outra
--                          pessoa e usar o bot para mandar mensagem a ela.
--
-- O front não usa nenhuma dessas permissões. Toda escrita passa pela API, que
-- usa a service_role e não depende de policy. Leitura continua liberada.
-- =============================================================================

drop policy if exists "assets: insert own"        on public.assets;
drop policy if exists "assets: delete own"        on public.assets;
drop policy if exists "user_profiles: update own" on public.user_profiles;


-- Limite de ativos no próprio banco, valendo para qualquer caminho de escrita,
-- inclusive a service_role. A API checa antes só para devolver uma mensagem
-- legível; quem garante é o trigger.
--
-- O advisory lock serializa inserções do mesmo usuário: sem ele, duas
-- requisições simultâneas com 29 ativos contariam 29 ao mesmo tempo e as
-- duas passariam.
create or replace function public.limitar_ativos_por_usuario()
returns trigger as $$
begin
    perform pg_advisory_xact_lock(hashtext(new.user_id::text));

    if (select count(*) from public.assets where user_id = new.user_id) >= 30 then
        raise exception 'Limite de 30 ativos por conta atingido.'
            using errcode = 'check_violation';
    end if;

    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_assets_limite on public.assets;
create trigger trg_assets_limite
    before insert on public.assets
    for each row execute function public.limitar_ativos_por_usuario();


-- O nome vem do metadata do cadastro, que o cliente controla: sem corte, dava
-- para criar conta com um nome de megabytes que depois vai para os e-mails.
-- Mesmo teto da API (120).
create or replace function public.handle_new_user()
returns trigger as $$
begin
    insert into public.user_profiles (id, full_name)
    values (
        new.id,
        left(nullif(trim(new.raw_user_meta_data->>'full_name'), ''), 120)
    );

    return new;
end;
$$ language plpgsql security definer;
