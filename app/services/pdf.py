import io
import logging
import re

import pdfplumber

logger = logging.getLogger(__name__)

_MAX_CHARS = 40_000
_HEX_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


def _clean(text: str) -> str:
    """Remove linhas que são apenas hex codes de cor (artefato do pdfplumber em PDFs com design)."""
    lines = [ln for ln in text.splitlines() if not _HEX_COLOR_RE.match(ln.strip())]
    return "\n".join(lines)


def extract_text(pdf_bytes: bytes) -> str:
    """
    Extrai o texto de um PDF em bytes, página por página.
    Trunca em _MAX_CHARS e remove artefatos de cor (hex codes) do pdfplumber.
    Retorna string vazia se o PDF não contiver texto extraível (ex: PDF escaneado).
    """
    text_parts = []
    total_chars = 0

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = _clean(page.extract_text() or "")
            text_parts.append(page_text)
            total_chars += len(page_text)

            if total_chars >= _MAX_CHARS:
                logger.info("Limite de caracteres atingido, PDF truncado para processamento.")
                break

    full_text = "\n".join(text_parts).strip()

    if not full_text:
        logger.warning("Nenhum texto extraível encontrado no PDF (possível PDF escaneado).")

    return full_text[:_MAX_CHARS]
