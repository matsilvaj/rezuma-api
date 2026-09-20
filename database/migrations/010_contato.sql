-- =============================================================================
-- 010: mensagens do formulário de contato
--
-- A mensagem é gravada aqui antes de qualquer tentativa de envio de e-mail.
-- O aviso por SMTP é conveniência; esta tabela é a fonte da verdade, para
-- nenhum feedback se perder por falha de entrega.
--
-- Sem policy nenhuma de propósito: com RLS ligada e nenhuma policy, ninguém
-- lê nem escreve com a chave anon. Só a API, que usa service_role, enxerga.
-- =============================================================================

create table if not exists public.contact_messages (
    id          uuid        primary key default uuid_generate_v4(),
    nome        text        not null,
    email       text        not null,
    mensagem    text        not null,
    -- Guardado para reconhecer abuso vindo da mesma origem. É dado pessoal,
    -- então sai junto na limpeza periódica das mensagens antigas.
    ip          text,
    lida        boolean     not null default false,
    created_at  timestamptz not null default now()
);

alter table public.contact_messages enable row level security;

create index if not exists idx_contact_messages_created_at
    on public.contact_messages(created_at desc);
