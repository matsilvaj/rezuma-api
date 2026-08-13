import json
import logging

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
_MODEL = "claude-haiku-4-5-20251001"

# ── Schemas de métricas extraídas por tipo de documento ───────────────────

_METRICS_SCHEMAS: dict[str, dict] = {
    "relatorio_gerencial": {
        "rendimento_por_cota": "float | null — R$/cota distribuído",
        "dy_percentual": "float | null — dividend yield do mês (%)",
        "dy_anualizado": "float | null — DY anualizado (%)",
        "valor_patrimonial_cota": "float | null — VPC em R$",
        "pvp": "float | null — preço sobre valor patrimonial (ex: 0.97 = 97%)",
        "vacancia_percentual": "float | null — % de área vaga",
        "inadimplencia_percentual": "float | null — % de inadimplência",
        "patrimonio_liquido": "float | null — PL total em R$",
        "mes_referencia": "string | null — ex: '07/2026'",
    },
    "informe_mensal": {
        "rendimento_por_cota": "float | null — R$/cota distribuído",
        "dy_percentual": "float | null — dividend yield do período",
        "vacancia_percentual": "float | null — % de área vaga",
        "inadimplencia_percentual": "float | null — % de inadimplência",
        "patrimonio_liquido": "float | null — PL total em R$",
        "mes_referencia": "string | null — ex: '01/2025'",
    },
    "itr": {
        "receita_liquida": "float | null — em R$",
        "lucro_liquido": "float | null — em R$",
        "ebitda": "float | null — em R$",
        "margem_liquida_percentual": "float | null",
        "divida_liquida_ebitda": "float | null",
        "trimestre_referencia": "string | null — ex: '1T2025'",
    },
    "dfp": {
        "receita_liquida": "float | null — em R$",
        "lucro_liquido": "float | null — em R$",
        "ebitda": "float | null — em R$",
        "margem_liquida_percentual": "float | null",
        "divida_liquida_ebitda": "float | null",
        "ano_referencia": "string | null — ex: '2024'",
    },
    "apresentacao_resultados": {
        "receita_liquida": "float | null — em R$",
        "lucro_liquido": "float | null — em R$",
        "ebitda": "float | null — em R$",
        "margem_ebitda_percentual": "float | null",
        "margem_liquida_percentual": "float | null",
        "divida_liquida_ebitda": "float | null",
        "dividendo_por_acao": "float | null — R$/ação",
        "trimestre_referencia": "string | null — ex: '2T2026'",
        "guidance_receita": "string | null — guidance de receita se divulgado",
    },
    "fato_relevante": {
        "tipo_evento": "string | null — ex: 'dividendo_extraordinario', 'aquisicao', 'guidance', 'mudanca_gestao', 'oferta_publica'",
        "impacto": "string | null — ex: 'positivo', 'negativo', 'neutro'",
    },
}

# ── Formatos de resumo por tipo de documento ──────────────────────────────

_SUMMARY_FORMATS: dict[str, str] = {
    "relatorio_gerencial": """\
📊 {ticker} — MM/AAAA

[1 frase respondendo: foi um bom mês para quem investe aqui? Ex: "O fundo pagou bem e a carteira continua saudável" ou "Mês fraco — o rendimento caiu e a vacância subiu"]

💰 Você recebeu R$ X,XX por cota esse mês
→ Quem tem 1.000 cotas recebeu R$ X.XXX
[se houver métricas anteriores: foi ▲ mais ou ▼ menos que o mês passado — explique o motivo em 1 frase simples]

[se P/VP disponível: 💡 A cota está sendo negociada X% [mais barata / mais cara] que o valor real dos ativos do fundo — [1 frase do que isso significa para quem compra agora]]

[2 frases simples explicando o que garante (ou ameaça) esse rendimento: quem são os inquilinos/devedores, se os contratos são longos, se há imóveis vazios. Sem jargão.]

[se houver evento relevante: ⚠️ Fique de olho: 1 frase sobre risco ou evento próximo em linguagem direta]\
""",

    "informe_mensal": """\
📊 {ticker} — MM/AAAA

[1 frase: foi um bom mês para quem investe aqui?]

💰 Você recebeu R$ X,XX por cota esse mês
→ Quem tem 1.000 cotas recebeu R$ X.XXX
[se houver métricas anteriores: ▲ mais ou ▼ menos que o mês passado]

[2 frases simples: o que sustenta o rendimento e o que pode mudar. Sem jargão.]
[se houver risco relevante: ⚠️ 1 frase direta]

""",

    "itr": """\
📈 {ticker} — XTaaaa

[1 frase respondendo: o que aconteceu no trimestre e foi bom ou ruim para quem investe aqui? Em linguagem simples.]

[2 frases explicando o que aconteceu e o que isso significa para o acionista — dividendos, dívida, crescimento. Use números só se ajudarem a entender, sempre com contexto.]
[se houver métricas anteriores: mencione se melhorou ou piorou vs trimestre anterior em 1 frase]

⚠️ [1 frase sobre o principal risco em linguagem direta]\
""",

    "dfp": """\
📈 {ticker} — aaaa

[1 frase respondendo: o que aconteceu no ano e foi bom ou ruim para quem investe aqui? Em linguagem simples.]

[2 frases explicando o que aconteceu e o que isso significa para o acionista — dividendos pagos, se a empresa cresceu, se a dívida subiu ou caiu. Use números só com contexto.]
[se houver métricas anteriores: mencione se melhorou ou piorou vs ano anterior em 1 frase]

⚠️ [1 frase sobre o principal risco em linguagem direta]\
""",

    "apresentacao_resultados": """\
📈 {ticker} — XTaaaa

[1 frase respondendo: o que aconteceu no trimestre e foi bom ou ruim para quem investe aqui? Ex: "O Banco do Brasil teve um trimestre difícil — o lucro caiu por causa do aumento de calotes no agronegócio."]

[2-3 frases sobre o que aconteceu e o que isso significa para o acionista: dividendos, dívida, crescimento. Sem jargão. Cada número com contexto de se é bom ou ruim.]
[se houver métricas anteriores: 1 frase sobre melhora ou piora vs trimestre anterior]

[se houver guidance: 📌 O que a empresa espera para os próximos meses: 1 frase simples]

⚠️ [1 frase sobre o principal risco em linguagem direta]\
""",

    "fato_relevante": """\
🔔 {ticker}

[1-2 frases: o que aconteceu em linguagem simples, e se é boa ou má notícia para quem tem essa ação/cota]

[2 frases sobre o que isso muda na prática: vai afetar o dividendo? aumenta o risco? é oportunidade?]
[se houver risco: ⚠️ 1 frase direta]\
""",
}

_SYSTEM_PROMPT = """\
Você traduz relatórios financeiros em mensagens curtas e simples para investidores brasileiros que não têm formação financeira.

Imagine que você está explicando para um amigo por WhatsApp. Ele investe para ter renda extra, assiste vídeos no YouTube sobre finanças e não tem tempo para ler relatórios. Ele precisa saber em 1 minuto: o que aconteceu com o meu investimento?

REGRAS OBRIGATÓRIAS:
1. Máximo de 150 palavras no resumo completo. Seja conciso.
2. Proibido usar siglas sem explicar imediatamente. Exemplos corretos: "financiamentos imobiliários (CRIs)", "o valor dos imóveis por cota (VPC)". Siglas proibidas sem explicação: WALE, LTV, BTS, FoF, cap rate, NII, FFO.
3. Nunca liste números soltos. Todo número precisa de contexto — se é bom ou ruim e por quê: "dívida caindo pelo 3º trimestre seguido — a empresa está mais saudável" é útil. "Dívida/EBITDA: 2,1x" não diz nada para o leigo.
4. Comece com uma frase que responda: o que aconteceu e foi bom ou ruim para quem investe aqui?
5. Sempre use "você" para se dirigir ao leitor.
6. NUNCA faça recomendações de compra, venda ou manutenção. Você apenas traduz o que aconteceu e o que significa — a decisão é do investidor.
7. Use apenas dados do documento.
8. Retorne APENAS JSON válido sem markdown.\
"""


def summarize(
    ticker: str,
    document_type: str,
    text: str,
    previous_metrics: dict | None = None,
) -> tuple[str, dict]:
    """
    Gera resumo estruturado e extrai métricas-chave do documento.
    Retorna (resumo_texto, métricas_dict).
    O resumo inclui comparação com o período anterior quando previous_metrics é fornecido.
    """
    if not text.strip():
        logger.warning(f"Texto vazio para {ticker} — resumo não gerado.")
        return "", {}

    schema = _METRICS_SCHEMAS.get(document_type, _METRICS_SCHEMAS["fato_relevante"])
    fmt = _SUMMARY_FORMATS.get(document_type, _SUMMARY_FORMATS["fato_relevante"]).format(ticker=ticker)

    previous_context = ""
    if previous_metrics:
        previous_context = (
            f"\n\nMÉTRICAS DO PERÍODO ANTERIOR (use para mostrar variações no resumo):\n"
            f"{json.dumps(previous_metrics, ensure_ascii=False)}"
        )

    user_prompt = (
        f"Analise o documento abaixo do ativo {ticker} (tipo: {document_type}).\n\n"
        f"Retorne JSON com dois campos:\n"
        f"- \"summary\": resumo seguindo EXATAMENTE este formato:\n{fmt}\n\n"
        f"- \"metrics\": métricas extraídas conforme este schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
        f"{previous_context}\n\n"
        f"DOCUMENTO:\n{text}"
    )

    logger.info(f"Gerando resumo para {ticker} ({document_type})...")

    try:
        max_tok = 2048 if document_type in ("relatorio_gerencial", "apresentacao_resultados", "itr", "dfp") else 1024
        message = _client.messages.create(
            model=_MODEL,
            max_tokens=max_tok,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if the model added them
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) >= 2 else raw
            if raw.startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
        summary = data.get("summary", "").strip()
        metrics = data.get("metrics", {})
        logger.info(f"Resumo gerado para {ticker}: {len(summary)} chars.")
        return summary, metrics
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Erro ao parsear resposta da IA para {ticker}: {e}")
        return "", {}
    except Exception as e:
        logger.error(f"Erro na chamada à IA para {ticker}: {e}")
        return "", {}
