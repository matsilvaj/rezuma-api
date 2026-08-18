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
DESTAQUE: [2-3 frases em prosa com **palavras-chave em negrito**. Responda: foi um bom mês? Inclua o rendimento por cota em negrito, compare com o mês anterior, e mencione o estado geral do fundo. Ex: "O fundo distribuiu **R$ X,XX por cota** esse mês, alta de X% frente a junho. A carteira segue saudável: **vacância de X%**, abaixo da média do setor, e contratos bem distribuídos entre grandes inquilinos."]

> [1 frase curta com o dado mais marcante, estruturada como: **parte numérica ou fato em negrito**, contexto em texto normal. Ex: "**68% dos contratos são atípicos**, garantindo renda previsível até 2028 mesmo em cenário de retração."]

MOVIMENTAÇÕES: [2-3 frases em prosa corrida com **palavras-chave em negrito**. Explique o que aconteceu de concreto: imóveis vendidos ou comprados, obras, inquilinos que saíram ou entraram, variação de receita. Seja específico.

ATENÇÃO: [1-2 frases sobre o principal risco ou ponto de atenção para o investidor. Ex: "A Cargill vai desocupar um galpão em janeiro de 2027, o que pode elevar a vacância para X%." Omita esta seção inteira se não houver risco relevante a destacar.]\
""",

    "informe_mensal": """\
DESTAQUE: [2-3 frases em prosa com **palavras-chave em negrito**: rendimento por cota em negrito, comparação com o mês anterior, e o principal fator que explica o resultado. Ex: "Você recebeu **R$ X,XX por cota** esse mês, **X% a mais** que no mês passado. O crescimento veio principalmente dos contratos de aluguel reajustados pelo IPCA."]

> [1 frase com o dado mais relevante em negrito e contexto em texto normal.]

MOVIMENTAÇÕES: [2 frases em prosa corrida com **palavras-chave em negrito**: o que sustenta o rendimento e o que pode mudar nos próximos meses.]

ATENÇÃO: [1-2 frases sobre risco ou ponto de atenção. Omita se não houver.]\
""",

    "itr": """\
DESTAQUE: [2-3 frases em prosa com **palavras-chave em negrito**: o que aconteceu no trimestre, se foi bom ou ruim, e os principais números. Ex: "Trimestre sólido: o **lucro líquido cresceu X%** para R$ Xbi e a **dívida caiu pelo terceiro período seguido**. A empresa está mais eficiente e com mais caixa para distribuir dividendos."]

> [1 frase com o número mais impactante em negrito e contexto em texto normal.]

MOVIMENTAÇÕES: [2-3 frases em prosa corrida com **palavras-chave em negrito**: receita, lucro, dívida, dividendos. Compare com o trimestre anterior.]

ATENÇÃO: [1-2 frases sobre risco ou guidance negativo. Omita se não houver.]\
""",

    "dfp": """\
DESTAQUE: [2-3 frases em prosa com **palavras-chave em negrito**: o que aconteceu no ano, se foi bom ou ruim, e os principais números comparados com o ano anterior. Ex: "Ano positivo: a **receita cresceu X%** e o **lucro atingiu R$ Xbi**, o maior da história da empresa. Os dividendos pagos também bateram recorde."]

> [1 frase com o número mais relevante do ano em negrito e contexto.]

MOVIMENTAÇÕES: [2-3 frases em prosa corrida com **palavras-chave em negrito**: receita, lucro, dívida, dividendos pagos vs ano anterior.]

ATENÇÃO: [1-2 frases sobre risco ou tendência negativa. Omita se não houver.]\
""",

    "apresentacao_resultados": """\
DESTAQUE: [2-3 frases em prosa com **palavras-chave em negrito** sobre o que aconteceu no trimestre. Inclua o principal número financeiro (lucro, receita ou dividendo), compare com o trimestre anterior, e diga se a empresa está melhorando ou piorando. Ex: "Trimestre sólido: o **lucro subiu X%** frente ao 2T25, mostrando recuperação após um período fraco. A **receita cresceu X%** e a margem líquida voltou a subir."]

> [1 frase com o número mais marcante em negrito e contexto.]

MOVIMENTAÇÕES: [2-3 frases em prosa corrida com **palavras-chave em negrito**: receita, lucro, dívida, dividendo por ação, melhora ou piora vs trimestre anterior. Mencione guidance se houver.]

ATENÇÃO: [1-2 frases sobre risco ou ponto de atenção. Omita se não houver.]\
""",

    "fato_relevante": """\
DESTAQUE: [2-3 frases em prosa com **palavras-chave em negrito**: o que aconteceu, se é boa ou má notícia, e o que muda para o investidor. Ex: "A empresa anunciou a **aquisição de X por R$ Xbi**, financiada com caixa próprio. Isso deve aumentar a receita a partir de 20XX e tem potencial de elevar os dividendos futuros."]

> [1 frase com o impacto mais direto para o investidor em negrito e contexto.]

MOVIMENTAÇÕES: [2 frases em prosa corrida com **palavras-chave em negrito**: o que muda na prática em dividendo, risco ou oportunidade.]

ATENÇÃO: [1-2 frases sobre risco. Omita se não houver.]\
""",
}

_SYSTEM_PROMPT = """\
Você traduz relatórios financeiros em mensagens curtas e simples para investidores brasileiros que não têm formação financeira.

Imagine que você está explicando para um amigo. Ele investe para ter renda extra e não tem tempo para ler relatórios. Ele precisa saber em 1 minuto: o que aconteceu com o meu investimento?

REGRAS OBRIGATÓRIAS:
1. Máximo de 150 palavras no resumo completo. Seja conciso.
2. Proibido usar siglas sem explicar imediatamente. Exemplos corretos: "financiamentos imobiliários (CRIs)", "o valor dos imóveis por cota (VPC)". Siglas proibidas sem explicação: WALE, LTV, BTS, FoF, cap rate, NII, FFO.
3. Nunca liste números soltos. Todo número precisa de contexto — se é bom ou ruim e por quê.
4. Comece com uma frase que responda: o que aconteceu e foi bom ou ruim para quem investe aqui?
5. Sempre use "você" para se dirigir ao leitor.
6. NUNCA faça recomendações de compra, venda ou manutenção. Você traduz o que aconteceu — a decisão é do investidor.
7. Use apenas dados do documento.
8. Retorne APENAS JSON válido sem markdown.
9. NUNCA use o caractere "—" (travessão/em dash) nem "–" (en dash) no texto. Substitua por vírgula, dois-pontos ou reescreva a frase.
10. NUNCA use emojis, símbolos de bullet (◆ • → ▸) ou qualquer marcador de lista. Apenas prosa corrida.\
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
        f"- \"summary\": UMA STRING de texto puro (não objeto JSON) seguindo EXATAMENTE este formato "
        f"(substitua os colchetes pelo conteúdo real):\n{fmt}\n\n"
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
        summary_raw = data.get("summary", "")

        # Modelo às vezes retorna summary como objeto {DESTAQUE: ..., MOVIMENTAÇÕES: ...}
        # em vez de string — nesse caso, reconstrói a string manualmente
        if isinstance(summary_raw, dict):
            parts: list[str] = []
            destaque = summary_raw.get("DESTAQUE") or summary_raw.get("destaque", "")
            quote    = summary_raw.get("quote") or summary_raw.get(">", "")
            mov      = (
                summary_raw.get("MOVIMENTAÇÕES")
                or summary_raw.get("MOVIMENTACOES")
                or summary_raw.get("movimentacoes", "")
            )
            if isinstance(destaque, list):
                destaque = " ".join(str(x) for x in destaque)
            if isinstance(mov, list):
                mov = " ".join(str(x) for x in mov)
            if destaque:
                parts.append(f"DESTAQUE: {destaque}")
            if quote:
                parts.append(f"> {quote}")
            if mov:
                parts.append(f"MOVIMENTAÇÕES: {mov}")
            summary = "\n\n".join(parts).strip()
        else:
            summary = str(summary_raw).strip()

        metrics = data.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        logger.info(f"Resumo gerado para {ticker}: {len(summary)} chars.")
        return summary, metrics
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Erro ao parsear resposta da IA para {ticker}: {e}")
        return "", {}
    except Exception as e:
        logger.error(f"Erro na chamada à IA para {ticker}: {e}")
        return "", {}
