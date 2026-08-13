-- Migration 004: adiciona colunas de token para vinculação do Telegram
-- Execute no SQL Editor do Supabase

alter table public.user_profiles
    add column if not exists telegram_link_token             text,
    add column if not exists telegram_link_token_expires_at  timestamptz;
