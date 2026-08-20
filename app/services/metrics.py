"""
Validação das métricas extraídas pela IA.

O risco aqui é de magnitude: balanço brasileiro publica em "R$ mil" ou
"R$ milhões", e o modelo tende a devolver o número como impresso na tabela.
R$ 1 milhão vira 1, e o dashboard mostra "R$1".

Percentuais, razões e valores por cota são imunes ao problema: se a tabela
está em milhares, o percentual sai igual e R$ 0,89 por cota continua 0,89.
Só os absolutos monetários precisam de tratamento.

A regra que orienta o módulo: número errado é pior que número nenhum. Quando
qualquer verificação falha, a métrica é descartada e some da coluna — o valor
continua no texto do resumo, onde ao menos aparece com contexto.
"""

import logging
import unicodedata

logger = logging.getLogger(__name__)

# Campos em dinheiro absoluto: os únicos sujeitos a erro de unidade.
ABSOLUTE_MONEY_KEYS = {
    "receita_liquida",
    "lucro_liquido",
    "ebitda",
    "patrimonio_liquido",
}

# Piso por campo. Receita e patrimônio de uma listada ou de um FII não podem
# ser minúsculos: valor abaixo do piso denuncia unidade errada.
#
# Lucro e EBITDA ficam de fora do piso de propósito — podem ser legitimamente
# pequenos, zero ou negativos numa margem apertada ou num trimestre ruim, e um
# piso ali descartaria número correto. Para esses, a proteção é a unidade
# confirmada no documento mais a trava cruzada da margem.
ABSOLUTE_FLOORS = {
    "receita_liquida": 1_000_000.0,
    "patrimonio_liquido": 1_000_000.0,
}
ABSOLUTE_MAX = 1e13

_MULTIPLIER = {
    "unidades": 1.0,
    "milhares": 1_000.0,
    "milhoes": 1_000_000.0,
    "bilhoes": 1_000_000_000.0,
}

# Faixas plausíveis para os campos sem unidade monetária. Fora disso o valor
# está corrompido de alguma outra forma e também é descartado.
RANGES: dict[str, tuple[float, float]] = {
    "rendimento_por_cota":       (0.0001, 500.0),
    "dividendo_por_acao":        (0.0001, 500.0),
    "valor_patrimonial_cota":    (0.01, 100_000.0),
    "dy_percentual":             (0.0, 100.0),
    "dy_anualizado":             (0.0, 200.0),
    "vacancia_percentual":       (0.0, 100.0),
    "inadimplencia_percentual":  (0.0, 100.0),
    "margem_liquida_percentual": (-500.0, 100.0),
    "margem_ebitda_percentual":  (-500.0, 100.0),
    "pvp":                       (0.01, 20.0),
    "divida_liquida_ebitda":     (-50.0, 100.0),
}


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _unidade_confirmada(unidade: str, fonte: str) -> bool:
    """
    Confere se o trecho citado do documento sustenta a unidade declarada.

    Sem isso estaríamos confiando na palavra do modelo. Com isso, ele precisa
    apontar onde leu — e "milhares" e "milhões" são distinguidos por tokens
    inteiros, porque um é prefixo confuso do outro.
    """
    t = _sem_acento(fonte)
    if unidade == "milhoes":
        return "milhoes" in t or "milhao" in t
    if unidade == "bilhoes":
        return "bilhoes" in t or "bilhao" in t
    if unidade == "milhares":
        return "milhares" in t or "milhar" in t or "mil reais" in t or "r$ mil" in t
    if unidade == "unidades":
        return True
    return False


def _numero(valor) -> float | None:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    return None


def normalize_metrics(metrics: dict | None, ticker: str = "") -> dict:
    """
    Converte os absolutos para reais e descarta o que não passa na validação.

    Consome os campos auxiliares unidade_valores e unidade_fonte: eles servem
    à conferência e não são gravados no banco.
    """
    if not metrics or not isinstance(metrics, dict):
        return {}

    limpo = dict(metrics)
    unidade = str(limpo.pop("unidade_valores", "") or "").strip().lower()
    fonte   = str(limpo.pop("unidade_fonte", "") or "")

    unidade = _sem_acento(unidade) if unidade else ""
    confiavel = bool(unidade) and unidade in _MULTIPLIER and _unidade_confirmada(unidade, fonte)
    fator = _MULTIPLIER.get(unidade, 1.0) if confiavel else None

    saida: dict = {}

    for chave, valor in limpo.items():
        # Campos de texto (mes_referencia, trimestre_referencia, guidance...)
        # passam direto: não são número e não entram na coluna de métricas.
        if isinstance(valor, str):
            saida[chave] = valor
            continue

        n = _numero(valor)
        if n is None:
            continue

        if chave in ABSOLUTE_MONEY_KEYS:
            if fator is None:
                # Sem unidade confirmada não dá para afirmar a ordem de
                # grandeza: 2.000 tanto pode ser R$ 2 mil quanto R$ 2 bilhões.
                logger.info(f"{ticker}: {chave} descartada, unidade não confirmada.")
                continue
            convertido = n * fator
            piso = ABSOLUTE_FLOORS.get(chave, 0.0)
            if abs(convertido) > ABSOLUTE_MAX or abs(convertido) < piso:
                logger.info(
                    f"{ticker}: {chave} descartada, valor implausível "
                    f"({n} × {fator:.0f} = {convertido:.0f})."
                )
                continue
            saida[chave] = convertido
            continue

        faixa = RANGES.get(chave)
        if faixa and not (faixa[0] <= n <= faixa[1]):
            logger.info(f"{ticker}: {chave} descartada, fora da faixa plausível ({n}).")
            continue

        saida[chave] = n

    _checar_margem(saida, ticker)
    return saida


def _checar_margem(m: dict, ticker: str) -> None:
    """
    Trava cruzada: lucro dividido por receita tem que bater com a margem
    informada. Quando não bate, os absolutos estão furados e a margem não,
    então descarta os absolutos e preserva o percentual.

    Remove os campos direto no dicionário recebido.
    """
    receita = m.get("receita_liquida")
    lucro   = m.get("lucro_liquido")
    margem  = m.get("margem_liquida_percentual")

    if receita is None or lucro is None or margem is None:
        return
    if not receita:
        return

    calculada = lucro / receita * 100.0
    # Tolerância larga de propósito: margem divulgada costuma ser ajustada,
    # enquanto a calculada é contábil. Só acusa discrepância gritante.
    if abs(calculada - margem) > 15.0:
        logger.info(
            f"{ticker}: receita e lucro descartados, margem calculada "
            f"({calculada:.1f}%) diverge da informada ({margem:.1f}%)."
        )
        m.pop("receita_liquida", None)
        m.pop("lucro_liquido", None)
