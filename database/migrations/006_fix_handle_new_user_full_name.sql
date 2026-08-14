-- Atualiza o trigger de criação de usuário para capturar o full_name do metadata do Supabase Auth.
-- Sem isso, novos registros criavam o perfil sem nome, mesmo que o frontend enviasse o nome no signUp.

create or replace function public.handle_new_user()
returns trigger as $$
begin
    insert into public.user_profiles (id, full_name)
    values (new.id, new.raw_user_meta_data->>'full_name');

    insert into public.subscriptions (user_id)
    values (new.id);

    return new;
end;
$$ language plpgsql security definer;
