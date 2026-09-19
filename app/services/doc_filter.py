"""
Descarte de documentos redundantes antes do processamento.

Só remove o que é comprovadamente repetido: versão em outro idioma do mesmo
documento e repostagem com título idêntico. Documentos que tratam do mesmo
evento por ângulos diferentes (release, análise de desempenho, balanço
auditado) são conteúdos distintos e permanecem.

Roda antes da chamada à IA, então também evita o custo de resumir duas vezes
o mesmo texto.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Versões traduzidas: a companhia publica o mesmo documento em português e em
# inglês. O conteúdo já entra pela versão em português.
_IDIOMA_ESTRANGEIRO = (
    r"vers[ao][o~]?\s*(em\s*)?ingl[e^]s",
    r"english\s*version",
    r"\benglish\b",
    r"\bingles\b",
    r"\(\s*en\s*\)",
    r"\ben_us\b",
)


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def is_versao_estrangeira(title: str) -> bool:
    """
    Título indica versão traduzida do documento.

    "Versão Português" não casa: o padrão exige menção explícita a inglês.
    """
    t = _normalizar(title)
    return any(re.search(p, t) for p in _IDIOMA_ESTRANGEIRO)


def filter_documents(documents: list[dict], ticker: str = "") -> list[dict]:
    """
    Devolve os documentos sem versões estrangeiras nem repostagens.

    Repostagem é título idêntico no mesmo tipo de documento, a CVM aceita
    reenvio corrigido, e os dois ficam listados. Mantém o mais recente.
    """
    if not documents:
        return documents

    mantidos: dict[tuple[str, str], dict] = {}
    descartados_idioma = 0
    descartados_repost = 0

    for doc in documents:
        titulo = doc.get("title", "") or ""

        if is_versao_estrangeira(titulo):
            descartados_idioma += 1
            continue

        chave = (doc.get("document_type", ""), _normalizar(titulo))
        anterior = mantidos.get(chave)
        if anterior is None:
            mantidos[chave] = doc
            continue

        descartados_repost += 1
        # Empate no título: fica a publicação mais recente
        if str(doc.get("published_at", "")) > str(anterior.get("published_at", "")):
            mantidos[chave] = doc

    if descartados_idioma or descartados_repost:
        logger.info(
            f"{ticker}: {len(documents)} documento(s) → {len(mantidos)} após filtro "
            f"({descartados_idioma} em outro idioma, {descartados_repost} repostagem)."
        )

    # Preserva a ordem original de chegada
    ids_mantidos = {id(d) for d in mantidos.values()}
    return [d for d in documents if id(d) in ids_mantidos]
