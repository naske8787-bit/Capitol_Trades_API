import re
import time
import os

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestBarRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

from config import (
    CAPITOL_TRADES_API_URL,
    CAPITOL_TRADES_MAX_PAGES,
    STOCK_DATA_CACHE_TTL_SECONDS,
    ALPACA_API_KEY,
    ALPACA_API_SECRET,
    ALPACA_DATA_FEED,
)

_alpaca_data_client = None


def _get_alpaca_data_client():
    global _alpaca_data_client
    if _alpaca_data_client is None and ALPACA_API_KEY and ALPACA_API_SECRET:
        _alpaca_data_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
    return _alpaca_data_client

_CAPITOL_TRADES_CACHE = []
_STOCK_DATA_CACHE = {}
_LAST_FETCH_TS = 0.0
_LAST_WARNING_TS = 0.0
_CACHE_TTL_SECONDS = 300
_WARNING_COOLDOWN_SECONDS = 300
_REQUEST_TIMEOUT_SECONDS = 10
_BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _extract_symbol(asset_text):
    """Extract a ticker symbol from asset text like 'Microsoft Corp MSFT:US'."""
    match = re.search(r"\b([A-Z]{1,5})(?=:[A-Z]{2}\b)", asset_text or "")
    return match.group(1) if match else None


def _normalize_json_payload(payload):
    """Normalize JSON API data into the bot's expected trade format."""
    if isinstance(payload, dict):
        trades = payload.get("data", payload.get("results", payload.get("trades", [])))
    elif isinstance(payload, list):
        trades = payload
    else:
        trades = []

    normalized = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue

        asset_text = str(
            trade.get("asset")
            or trade.get("issuer")
            or trade.get("ticker")
            or trade.get("symbol")
            or ""
        )
        symbol = trade.get("symbol") or _extract_symbol(asset_text)
        action = str(trade.get("action") or trade.get("trade_type") or trade.get("type") or "").lower()

        normalized.append(
            {
                **trade,
                "asset": asset_text,
                "symbol": symbol.upper() if isinstance(symbol, str) else symbol,
                "action": action,
            }
        )

    return normalized


def _parse_trade_rows_from_html(html):
    """Parse the public Capitol Trades website HTML into trade dictionaries."""
    soup = BeautifulSoup(html, "html.parser")
    trades = []

    for row in soup.select("tbody > tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 7:
            continue

        asset_text = cells[1]
        trades.append(
            {
                "politician": cells[0],
                "asset": asset_text,
                "symbol": _extract_symbol(asset_text),
                "published": cells[2] if len(cells) > 2 else None,
                "traded": cells[3] if len(cells) > 3 else None,
                "owner": cells[5] if len(cells) > 5 else None,
                "action": cells[6].strip().lower(),
                "range": cells[7] if len(cells) > 7 else None,
            }
        )

    return trades


def _dedupe_trades(trades):
    """Remove duplicate trade records while preserving order."""
    seen = set()
    unique_trades = []

    for trade in trades:
        key = (
            trade.get("politician"),
            trade.get("asset"),
            trade.get("symbol"),
            trade.get("traded"),
            trade.get("action"),
            trade.get("range"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_trades.append(trade)

    return unique_trades


def _fetch_public_site_trades(base_url, max_pages):
    """Fetch and combine multiple public Capitol Trades website pages."""
    combined = []

    for page in range(1, max_pages + 1):
        response = requests.get(
            f"{base_url}/trades?pageSize=96&page={page}",
            headers=_BROWSER_HEADERS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        page_trades = _parse_trade_rows_from_html(response.text)
        if not page_trades:
            break
        combined.extend(page_trades)
        if len(page_trades) < 96:
            break

    return _dedupe_trades(combined)


def fetch_capitol_trades():
    """Fetch recent Capitol Trades data from the configured source.

    Supports either a JSON API or the public website HTML and uses a short-lived
    cache so repeated symbol checks do not spam the network or logs.
    """
    global _CAPITOL_TRADES_CACHE, _LAST_FETCH_TS, _LAST_WARNING_TS

    now = time.time()
    if now - _LAST_FETCH_TS < _CACHE_TTL_SECONDS:
        return _CAPITOL_TRADES_CACHE

    base_url = CAPITOL_TRADES_API_URL.rstrip("/")
    request_url = f"{base_url}/trades"

    try:
        if "www.capitoltrades.com" in base_url:
            trades = _fetch_public_site_trades(base_url, CAPITOL_TRADES_MAX_PAGES)
        else:
            response = requests.get(
                request_url,
                headers=_BROWSER_HEADERS,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            if "json" in content_type:
                trades = _normalize_json_payload(response.json())
            else:
                trades = _parse_trade_rows_from_html(response.text)

        _CAPITOL_TRADES_CACHE = _dedupe_trades(trades)
        _LAST_FETCH_TS = now
        return _CAPITOL_TRADES_CACHE
    except (requests.RequestException, ValueError) as e:
        fallback_url = "https://www.capitoltrades.com"
        if base_url != fallback_url:
            try:
                trades = _fetch_public_site_trades(fallback_url, CAPITOL_TRADES_MAX_PAGES)
                _CAPITOL_TRADES_CACHE = trades
                _LAST_FETCH_TS = now
                return trades
            except requests.RequestException as fallback_error:
                e = fallback_error

        if now - _LAST_WARNING_TS >= _WARNING_COOLDOWN_SECONDS:
            print(f"Warning: Could not fetch Capitol Trades data from {CAPITOL_TRADES_API_URL}: {e}")
            _LAST_WARNING_TS = now
        _LAST_FETCH_TS = now
        return _CAPITOL_TRADES_CACHE

def fetch_realtime_price(symbol):
    """Fetch the latest real-time price for a symbol using Alpaca's market data API.

    Falls back to yfinance if Alpaca credentials are not configured or the request fails.
    """
    client = _get_alpaca_data_client()
    if client is not None:
        try:
            request = StockLatestBarRequest(symbol_or_symbols=symbol, feed=ALPACA_DATA_FEED)
            bars = client.get_stock_latest_bar(request)
            bar = bars.get(symbol)
            if bar is not None:
                return float(bar.close)
        except Exception as e:
            print(f"Alpaca real-time price fetch failed for {symbol}, falling back to yfinance: {e}")

    # yfinance fallback
    try:
        data = yf.download(symbol, period="5d", progress=False, auto_adjust=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        price = data["Close"].iloc[-1]
        return float(price.item() if hasattr(price, "item") else price)
    except Exception as e:
        print(f"yfinance price fetch also failed for {symbol}: {e}")
        return None


def fetch_stock_data(symbol, period="1y", start=None, end=None, use_cache=True):
    """Fetch historical stock data using yfinance.

    Supports either a relative `period` (used by the live strategy) or explicit
    `start` / `end` dates (used by backtesting). Live requests are cached briefly
    to avoid repeated downloads for each symbol check.
    """
    cache_key = (str(symbol).upper(), period, start, end)
    now = time.time()

    if use_cache and start is None and end is None:
        cached = _STOCK_DATA_CACHE.get(cache_key)
        if cached and now - cached[0] < STOCK_DATA_CACHE_TTL_SECONDS:
            return cached[1].copy()

    download_kwargs = {"progress": False}
    if start is not None or end is not None:
        if start is not None:
            download_kwargs["start"] = start
        if end is not None:
            download_kwargs["end"] = end
    else:
        download_kwargs["period"] = period

    data = yf.download(symbol, **download_kwargs)
    if isinstance(data, pd.Series):
        data = data.to_frame()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if use_cache and start is None and end is None:
        _STOCK_DATA_CACHE[cache_key] = (now, data.copy())
    return data

def preprocess_data(data):
    """Basic preprocessing for stock data."""
    data = data.dropna()
    data['Returns'] = data['Close'].pct_change()
    return data