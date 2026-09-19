"""
Validação das métricas extraídas pela IA.

O risco é de magnitude. Balanço brasileiro publica em "R$ mil" ou "R$ milhões",
e o modelo ora devolve o número como impresso na tabela, ora já converte por
conta própria. Quando ele converte e mesmo assim declara a unidade, o código
multiplica de novo e R$ 3,9 bilhões viram R$ 3.900 bilhões.

A defesa principal é ancorar no próprio texto do resumo: na prosa o modelo
escreve "R$ 3,9 bilhões" com a escala certa, porque ali ele está redigindo, não
preenchendo campo. Comparar o número estruturado com os valores citados no texto
pega o erro sem depender de o modelo seguir instrução, e, quando o valor cru
casa com a prosa, permite recuperar em vez de descartar.

Percentuais, razões e valores por cota são imunes ao problema: se a tabela está
em milhares, o percentual sai igual e R$ 0,89 por cota continua 0,89.

Regra que orienta o módulo: número errado é pior que número nenhum. Sem
conseguir afirmar o valor, a métrica é descartada, ela continua no texto do
resumo, onde ao menos aparece com contexto.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Campos em dinheiro absoluto: os únicos sujeitos a erro de escala.
ABSOLUTE_MONEY_KEYS = {
    "receita_liquida",
    "lucro_liquido",
    "ebitda",
    "patrimonio_liquido",
    "margem_financeira",
}

# Piso por campo. Receita e patrimônio de uma listada ou de um FII não podem
# ser minúsculos: valor abaixo do piso denuncia unidade errada.
#
# Lucro e EBITDA ficam de fora do piso de propósito, podem ser legitimamente
# pequenos, zero ou negativos numa margem apertada ou num trimestre ruim.
ABSOLUTE_FLOORS = {
    "receita_liquida": 1_000_000.0,
    "patrimonio_liquido": 1_000_000.0,
}

# Nenhuma empresa brasileira tem receita, lucro ou patrimônio acima de
# R$ 1 trilhão. Acima disso é erro de escala, não empresa grande.
ABSOLUTE_MAX = 1e12

# Margem de folga ao comparar com o texto: a prosa arredonda ("R$ 3,9 bilhões"
# para 3.912.456.000), então exigir igualdade exata reprovaria valor correto.
TOLERANCIA = 0.05

_MULTIPLIER = {
    "unidades": 1.0,
    "milhares": 1_000.0,
    "milhoes": 1_000_000.0,
    "bilhoes": 1_000_000_000.0,
}

RANGES: dict[str, tuple[float, float]] = {
    "rendimento_por_cota":         (0.0001, 500.0),
    "dividendo_por_acao":          (0.0001, 500.0),
    "valor_patrimonial_cota":      (0.01, 100_000.0),
    "dy_percentual":               (0.0, 100.0),
    "dy_anualizado":               (0.0, 200.0),
    "vacancia_percentual":         (0.0, 100.0),
    "inadimplencia_percentual":    (0.0, 100.0),
    "margem_liquida_percentual":   (-500.0, 100.0),
    "margem_ebitda_percentual":    (-500.0, 100.0),
    "roe_percentual":              (-200.0, 200.0),
    "indice_basileia":             (0.0, 100.0),
    "indice_eficiencia_percentual": (0.0, 200.0),
    "pvp":                         (0.01, 20.0),
    "divida_liquida_ebitda":       (-50.0, 100.0),
}

# Escalas escritas por extenso na prosa. Ordem importa no regex: "mil" é
# prefixo de "milhoes", então os termos longos vêm primeiro.
_ESCALAS = (
    ("trilhoes", 1e12), ("trilhao", 1e12),
    ("bilhoes", 1e9),   ("bilhao", 1e9),
    ("milhoes", 1e6),   ("milhao", 1e6),
    ("mil", 1e3),
)

_VALOR_TEXTO = re.compile(
    r"r\$\s*(\d[\d.,]*)\s*("
    + "|".join(termo for termo, _ in _ESCALAS)
    + r")?",
)


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _para_float(bruto: str) -> float | None:
    """
    Converte número escrito à brasileira: ponto separa milhar, vírgula separa
    decimal. "1.313" é mil trezentos e treze; "1,313" é um vírgula trezentos.
    """
    try:
        return float(bruto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def valores_no_texto(texto: str) -> list[float]:
    """
    Valores monetários citados na prosa, já convertidos para reais.

    "R$ 3,9 bilhões" devolve 3_900_000_000.0.
    """
    if not texto:
        return []

    escala_por_termo = dict(_ESCALAS)
    achados: list[float] = []

    for bruto, termo in _VALOR_TEXTO.findall(_sem_acento(texto)):
        n = _para_float(bruto)
        if n is None:
            continue
        achados.append(n * escala_por_termo.get(termo, 1.0))

    return achados


def _unidade_confirmada(unidade: str, fonte: str) -> bool:
    """
    Confere se o trecho citado do documento sustenta a unidade declarada.

    Sem isso estaríamos confiando na palavra do modelo. "milhares" e "milhões"
    são distinguidos por tokens inteiros, porque um é quase prefixo do outro.
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


def _casa_com(valor: float, ancoras: list[float]) -> bool:
    return any(
        abs(valor - a) <= max(abs(a) * TOLERANCIA, 1.0)
        for a in ancoras
    )


def _resolver_absoluto(
    chave: str,
    bruto: float,
    fator: float | None,
    ancoras: list[float],
    ticker: str,
) -> float | None:
    """
    Decide o valor final de um campo monetário absoluto.

    Com valores citados no texto, eles são a autoridade: tenta o número
    convertido e, se não casar, tenta o número cru, que é o caso de o modelo
    já ter convertido sozinho e ainda assim declarar a unidade. Sem citação no
    texto, cai nas regras de unidade, piso e teto.
    """
    candidatos: list[tuple[str, float]] = []
    if fator is not None:
        candidatos.append(("convertido", bruto * fator))
    candidatos.append(("cru", bruto))

    if ancoras:
        for nome, valor in candidatos:
            if _casa_com(valor, ancoras):
                if nome == "cru" and fator not in (None, 1.0):
                    logger.info(
                        f"{ticker}: {chave} veio já convertida pelo modelo; "
                        f"usando {valor:.0f} em vez de multiplicar de novo."
                    )
                return valor
        logger.info(
            f"{ticker}: {chave} descartada, nenhum valor do texto confere "
            f"(cru={bruto}, fator={fator})."
        )
        return None

    if fator is None:
        logger.info(f"{ticker}: {chave} descartada, unidade não confirmada e texto sem valor para conferir.")
        return None

    return bruto * fator


def normalize_metrics(metrics: dict | None, ticker: str = "", summary: str = "") -> dict:
    """
    Converte os absolutos para reais e descarta o que não passa na validação.

    summary: o texto do resumo, usado como âncora de escala. Sem ele a
    validação fica restrita à unidade declarada e às faixas.

    Consome os campos auxiliares unidade_valores e unidade_fonte: servem à
    conferência e não são gravados.
    """
    if not metrics or not isinstance(metrics, dict):
        return {}

    limpo = dict(metrics)
    unidade = _sem_acento(str(limpo.pop("unidade_valores", "") or "").strip())
    fonte   = str(limpo.pop("unidade_fonte", "") or "")

    confiavel = bool(unidade) and unidade in _MULTIPLIER and _unidade_confirmada(unidade, fonte)
    fator = _MULTIPLIER.get(unidade, 1.0) if confiavel else None

    ancoras = valores_no_texto(summary)
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
            final = _resolver_absoluto(chave, n, fator, ancoras, ticker)
            if final is None:
                continue
            piso = ABSOLUTE_FLOORS.get(chave, 0.0)
            if abs(final) > ABSOLUTE_MAX or abs(final) < piso:
                logger.info(f"{ticker}: {chave} descartada, valor implausível ({final:.0f}).")
                continue
            saida[chave] = final
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
    """
    receita = m.get("receita_liquida")
    lucro   = m.get("lucro_liquido")
    margem  = m.get("margem_liquida_percentual")

    if receita is None or lucro is None or margem is None or not receita:
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
