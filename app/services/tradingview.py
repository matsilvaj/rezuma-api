"""
TradingView scanner API — free, no auth required.
Returns market price and dividend yield for Brazilian assets.
Ticker format: "BMFBOVESPA:{TICKER}" e.g. "BMFBOVESPA:TRXF11"
"""
import logging

import httpx

logger = logging.getLogger(__name__)

_SCAN_URL = "https://scanner.tradingview.com/brazil/scan"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Content-Type": "application/json",
}

_COLUMNS = [
    "close",                          # current price
    "dividends_yield",                # annual DY %
    "dividends_yield_current",        # current DY %
    "dps_common_stock_prim_issue_fy", # dividends per share (FY)
    "market_cap_basic",               # market cap
]


async def fetch_quotes(tickers: list[str]) -> dict[str, dict]:
    """
    Fetches market data from TradingView for a list of B3 tickers.

    Returns dict keyed by ticker (uppercase, no exchange prefix):
      {
        "TRXF11": {"price": 81.35, "dy_anual": 13.62, "dy_atual": None, "dps": None, "market_cap": None},
        ...
      }
    Returns empty dict on failure.
    """
    if not tickers:
        return {}

    tv_tickers = [f"BMFBOVESPA:{t.upper()}" for t in tickers]
    body = {"symbols": {"tickers": tv_tickers}, "columns": _COLUMNS}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(_SCAN_URL, json=body, headers=_HEADERS)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"TradingView fetch falhou: {e}")
        return {}

    result: dict[str, dict] = {}
    for item in data.get("data", []):
        symbol = item["s"].replace("BMFBOVESPA:", "")
        vals = item.get("d", [])
        result[symbol] = {
            "price": vals[0] if len(vals) > 0 else None,
            "dy_anual": vals[1] if len(vals) > 1 else None,
            "dy_atual": vals[2] if len(vals) > 2 else None,
            "dps": vals[3] if len(vals) > 3 else None,
            "market_cap": vals[4] if len(vals) > 4 else None,
        }
    logger.info(f"TradingView: cotações obtidas para {list(result.keys())}")
    return result
