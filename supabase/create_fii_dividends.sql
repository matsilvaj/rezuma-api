-- Tabela de cache de dividendos de FIIs (buscados do FNET)
-- Uma linha por anúncio (ticker + data_base é a chave natural)
create table if not exists fii_dividends (
    id              uuid primary key default gen_random_uuid(),
    ticker          text not null,
    cnpj            text not null,
    valor_por_cota  numeric(12, 6) not null,
    data_base       date not null,           -- ex-dividend date
    data_pagamento  date,
    periodo         text,
    isento_ir       boolean not null default false,
    published_at    date,                    -- dataEntrega no FNET
    fetched_at      timestamptz not null default now(),

    unique (ticker, data_base)
);

create index if not exists fii_dividends_ticker_idx on fii_dividends (ticker, data_base desc);
