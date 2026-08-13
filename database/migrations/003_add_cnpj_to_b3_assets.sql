-- Migration 003: adiciona CNPJ em b3_assets para mapear FIIs no sistema da CVM
-- O CNPJ é necessário para buscar documentos na CVM (que não usa ticker como identificador)
-- Execute no SQL Editor do Supabase

alter table public.b3_assets
    add column cnpj text;
