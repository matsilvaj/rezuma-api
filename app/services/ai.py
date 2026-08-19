import json
import logging

import anthropic

from app.core.config import settings
from app.services.glossary import known_terms

logger = logging.getLogger(__name__)

_GLOSSARY_TERMS = ", ".join(known_terms())

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
DESTAQUE: [2 a 3 frases curtas. Traga o rendimento por cota em **negrito**, a variação frente ao mês anterior e o estado geral da carteira. Cada frase carrega uma informação nova.]

> [1 frase com o dado mais marcante do mês: o fato em **negrito** no início, o contexto em texto normal depois.]

MOVIMENTAÇÕES: [1 a 2 frases sobre o que mudou de concreto no período: compras, vendas, obras, entrada ou saída de inquilinos. Não repita nada que já apareceu no DESTAQUE.]

ATENÇÃO: [1 frase com o principal risco à frente. Omita esta linha inteira se o documento não apontar risco relevante.]\
""",

    "informe_mensal": """\
DESTAQUE: [2 a 3 frases curtas: rendimento por cota em **negrito**, comparação com o mês anterior e o fator que explica o resultado.]

> [1 frase com o dado mais relevante: fato em **negrito** no início, contexto depois.]

MOVIMENTAÇÕES: [1 a 2 frases sobre o que mudou no período e o que pode mudar adiante. Não repita o DESTAQUE.]

ATENÇÃO: [1 frase com o principal risco. Omita esta linha inteira se não houver risco relevante.]\
""",

    "itr": """\
DESTAQUE: [2 a 3 frases curtas: o resultado do trimestre com o número principal em **negrito**, a variação frente ao trimestre anterior e se a empresa melhorou ou piorou.]

> [1 frase com o número mais impactante em **negrito** no início e o contexto depois.]

MOVIMENTAÇÕES: [1 a 2 frases sobre o que mudou de concreto: dívida, investimentos, dividendos anunciados. Não repita o DESTAQUE.]

ATENÇÃO: [1 frase com o principal risco ou guidance negativo. Omita esta linha inteira se não houver.]

IMPACTO: [1 a 2 frases sobre o efeito prático disso para quem já tem o ativo: o que tende a acontecer com os rendimentos, com o risco ou com o caixa da empresa daqui para frente. Descreva a consequência, nunca o que fazer: não diga para comprar, vender ou manter, e não sugira que é hora de entrar ou sair. Omita esta linha inteira se o documento não permitir afirmar nada concreto.]\
""",

    "dfp": """\
DESTAQUE: [2 a 3 frases curtas: o resultado do ano com o número principal em **negrito**, comparação com o ano anterior e a tendência geral.]

> [1 frase com o número mais relevante do ano em **negrito** no início e o contexto depois.]

MOVIMENTAÇÕES: [1 a 2 frases sobre o que mudou de concreto no ano: dívida, dividendos pagos, investimentos. Não repita o DESTAQUE.]

ATENÇÃO: [1 frase com o principal risco ou tendência negativa. Omita esta linha inteira se não houver.]

IMPACTO: [1 a 2 frases sobre o efeito prático disso para quem já tem o ativo: o que tende a acontecer com os rendimentos, com o risco ou com o caixa da empresa daqui para frente. Descreva a consequência, nunca o que fazer: não diga para comprar, vender ou manter, e não sugira que é hora de entrar ou sair. Omita esta linha inteira se o documento não permitir afirmar nada concreto.]\
""",

    "apresentacao_resultados": """\
DESTAQUE: [2 a 3 frases curtas: o resultado do trimestre com o número principal em **negrito**, a variação frente ao trimestre anterior e se a empresa melhorou ou piorou.]

> [1 frase com o número mais marcante em **negrito** no início e o contexto depois.]

MOVIMENTAÇÕES: [1 a 2 frases sobre o que mudou de concreto: dívida, dividendo por ação, guidance divulgado. Não repita o DESTAQUE.]

ATENÇÃO: [1 frase com o principal risco. Omita esta linha inteira se não houver.]

IMPACTO: [1 a 2 frases sobre o efeito prático disso para quem já tem o ativo: o que tende a acontecer com os rendimentos, com o risco ou com o caixa da empresa daqui para frente. Descreva a consequência, nunca o que fazer: não diga para comprar, vender ou manter, e não sugira que é hora de entrar ou sair. Omita esta linha inteira se o documento não permitir afirmar nada concreto.]\
""",

    "fato_relevante": """\
DESTAQUE: [2 a 3 frases curtas: o que foi anunciado com o dado principal em **negrito**, se é boa ou má notícia e o que muda para quem investe.]

> [1 frase com o impacto mais direto para o investidor em **negrito** no início e o contexto depois.]

MOVIMENTAÇÕES: [1 a 2 frases sobre o que muda na prática em dividendo, risco ou oportunidade. Não repita o DESTAQUE.]

ATENÇÃO: [1 frase com o principal risco. Omita esta linha inteira se não houver.]

IMPACTO: [1 a 2 frases sobre o efeito prático disso para quem já tem o ativo: o que tende a acontecer com os rendimentos, com o risco ou com o caixa da empresa daqui para frente. Descreva a consequência, nunca o que fazer: não diga para comprar, vender ou manter, e não sugira que é hora de entrar ou sair. Omita esta linha inteira se o documento não permitir afirmar nada concreto.]\
""",
}

_SYSTEM_PROMPT = f"""\
Você traduz relatórios financeiros em mensagens curtas e simples para investidores brasileiros que não têm formação financeira.

Imagine que você está explicando para um amigo. Ele investe para ter renda extra e não tem tempo para ler relatórios. Ele precisa saber em 1 minuto: o que aconteceu com o meu investimento?

REGRAS OBRIGATÓRIAS:
1. Cada frase precisa carregar uma informação nova. Não encha linguiça, não repita entre seções, não escreva parágrafos longos. Traga o que o investidor precisa saber e pare.
2. O Rezuma exibe um glossário automático ao final do relatório. Os termos da lista abaixo já são explicados lá, então use-os com naturalidade, sem parafrasear nem abrir parênteses explicativos. Qualquer termo técnico que NÃO esteja na lista precisa ser explicado na hora, entre parênteses.

TERMOS JÁ COBERTOS PELO GLOSSÁRIO (use livremente, não explique):
{_GLOSSARY_TERMS}

3. Nunca liste números soltos. Todo número precisa de contexto — se é bom ou ruim e por quê.
4. NUNCA faça recomendações de compra, venda ou manutenção. Você traduz o que aconteceu — a decisão é do investidor.
5. Use apenas dados do documento.
6. Retorne APENAS JSON válido sem markdown.
7. NUNCA use o caractere "—" (travessão/em dash) nem "–" (en dash) no texto. Substitua por vírgula, dois-pontos ou reescreva a frase.
8. NUNCA use emojis, símbolos de bullet (◆ • → ▸) ou qualquer marcador de lista.

ESTRUTURA DO CAMPO "summary" (regra crítica):
O campo "summary" é UMA STRING de texto puro, nunca um objeto JSON.
Cada seção começa em sua própria linha, com uma linha em branco entre elas.
Os rótulos "DESTAQUE:", "MOVIMENTAÇÕES:", "ATENÇÃO:" e "IMPACTO:" são literais e devem ser escritos exatamente assim.
DESTAQUE e MOVIMENTAÇÕES são obrigatórios. ATENÇÃO e IMPACTO são opcionais: só aparecem no formato pedido e só quando há o que dizer.
IMPACTO, quando presente, é sempre a última seção.
NUNCA junte o conteúdo de várias seções em uma só.

EXEMPLO DE SAÍDA CORRETA para o campo "summary":

DESTAQUE: Resultado distribuível de **R$ 0,89 por cota**, alta de 3,5% frente ao 2T25. Vacância física mantida em **3,2%**, abaixo da média setorial de 6,1%. Fundo permanece entre os mais defensivos do segmento logístico.

> **Contratos atípicos representam 68% da receita**, conferindo previsibilidade de caixa até 2028 mesmo em cenário de retração do mercado imobiliário.

MOVIMENTAÇÕES: Gestão sinalizou **aquisição de dois galpões em Guarulhos**, com impacto positivo esperado no portfólio a partir do 1T26. Transações ainda sujeitas a aprovação de cotistas em assembleia extraordinária.

ATENÇÃO: A Cargill desocupa um galpão em janeiro de 2027, o que pode elevar a vacância para **3,8%**.

Note no exemplo: frases curtas, nenhuma repetição entre seções, negrito apenas nos dados que importam.\
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
