import re
import time
import os
import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

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
    CAPITOL_TRADES_REQUEST_RETRIES,
    CAPITOL_TRADES_RETRY_BACKOFF_SECONDS,
    CAPITOL_TRADES_FAILURE_RETRY_SECONDS,
    STOCK_DATA_CACHE_TTL_SECONDS,
    ALPACA_API_KEY,
    ALPACA_API_SECRET,
    ALPACA_DATA_FEED,
    EXTERNAL_RESEARCH_ENABLED,
    EXTERNAL_RESEARCH_CACHE_TTL_SECONDS,
    EXTERNAL_RESEARCH_MIN_HEADLINES,
    EXTERNAL_RESEARCH_MIN_SOURCES,
    EXTERNAL_RESEARCH_MIN_FRESH_RATIO,
    SEARCH_API_KEY,
    SEARCH_ENGINE,
    SEARCH_PROVIDER,
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
_CAPITOL_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "capitol_trades_cache.json")
_LAST_CACHE_LOAD_TS = 0.0


def _save_capitol_cache(trades):
    try:
        os.makedirs(os.path.dirname(_CAPITOL_CACHE_FILE), exist_ok=True)
        payload = {"saved_at": time.time(), "trades": trades or []}
        with open(_CAPITOL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        return


def _load_capitol_cache(max_age_seconds=86400):
    global _LAST_CACHE_LOAD_TS
    try:
        if not os.path.exists(_CAPITOL_CACHE_FILE):
            return []
        with open(_CAPITOL_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return []
        saved_at = float(payload.get("saved_at", 0.0) or 0.0)
        if saved_at > 0 and (time.time() - saved_at) > max_age_seconds:
            return []
        trades = payload.get("trades") or []
        _LAST_CACHE_LOAD_TS = time.time()
        return trades if isinstance(trades, list) else []
    except Exception:
        return []


def _request_with_retry(url, headers, timeout):
    attempts = max(1, int(CAPITOL_TRADES_REQUEST_RETRIES))
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            last_error = e
            if attempt < attempts:
                delay = max(0.1, float(CAPITOL_TRADES_RETRY_BACKOFF_SECONDS)) * attempt
                time.sleep(delay)
    raise last_error


def _normalize_base_url(base_url):
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path or "").strip().lower()
    if not host:
        return ""
    return f"https://{host}"


def _capitol_candidate_base_urls(configured_base_url):
    primary = _normalize_base_url(configured_base_url)
    if not primary:
        primary = "https://www.capitoltrades.com"

    parsed = urlparse(primary)
    host = parsed.netloc
    root = host[4:] if host.startswith("www.") else (host[4:] if host.startswith("api.") else host)

    candidates = [primary]
    if root:
        candidates.extend([
            f"https://www.{root}",
            f"https://{root}",
            f"https://api.{root}",
        ])

    seen = set()
    deduped = []
    for url in candidates:
        norm = _normalize_base_url(url)
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(norm)
    return deduped


def _is_public_site_base_url(base_url):
    host = urlparse(base_url).netloc
    return "capitoltrades.com" in host and not host.startswith("api.")


def _summarize_request_error(err):
    if isinstance(err, requests.exceptions.Timeout):
        return "timeout"
    if isinstance(err, requests.exceptions.HTTPError):
        status = getattr(getattr(err, "response", None), "status_code", None)
        return f"http {status}" if status else "http error"
    text = str(err).lower()
    if "temporary failure in name resolution" in text or "name or service not known" in text:
        return "dns resolution failure"
    if "connection aborted" in text:
        return "connection aborted"
    if "max retries exceeded" in text:
        return "max retries exceeded"
    return err.__class__.__name__


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
        response = _request_with_retry(
            f"{base_url}/trades?pageSize=96&page={page}",
            headers=_BROWSER_HEADERS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
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
    if not _CAPITOL_TRADES_CACHE:
        disk_cache = _load_capitol_cache()
        if disk_cache:
            _CAPITOL_TRADES_CACHE = _dedupe_trades(disk_cache)

    if now - _LAST_FETCH_TS < _CACHE_TTL_SECONDS:
        return _CAPITOL_TRADES_CACHE

    base_url = CAPITOL_TRADES_API_URL.rstrip("/")
    candidate_base_urls = _capitol_candidate_base_urls(base_url)
    attempt_failures = []

    try:
        trades = None
        for candidate_base_url in candidate_base_urls:
            request_url = f"{candidate_base_url}/trades"
            try:
                if _is_public_site_base_url(candidate_base_url):
                    trades = _fetch_public_site_trades(candidate_base_url, CAPITOL_TRADES_MAX_PAGES)
                else:
                    response = _request_with_retry(
                        request_url,
                        headers=_BROWSER_HEADERS,
                        timeout=_REQUEST_TIMEOUT_SECONDS,
                    )

                    content_type = response.headers.get("content-type", "").lower()
                    if "json" in content_type:
                        trades = _normalize_json_payload(response.json())
                    else:
                        trades = _parse_trade_rows_from_html(response.text)

                if trades:
                    break
            except (requests.RequestException, ValueError) as candidate_error:
                attempt_failures.append((candidate_base_url, candidate_error))
                continue

        if trades is None:
            if attempt_failures:
                raise attempt_failures[-1][1]
            raise requests.RequestException("No Capitol Trades endpoint candidates available")

        _CAPITOL_TRADES_CACHE = _dedupe_trades(trades)
        _save_capitol_cache(_CAPITOL_TRADES_CACHE)
        _LAST_FETCH_TS = now
        return _CAPITOL_TRADES_CACHE
    except (requests.RequestException, ValueError) as e:
        if not _CAPITOL_TRADES_CACHE:
            disk_cache = _load_capitol_cache(max_age_seconds=3 * 86400)
            if disk_cache:
                _CAPITOL_TRADES_CACHE = _dedupe_trades(disk_cache)

        if now - _LAST_WARNING_TS >= _WARNING_COOLDOWN_SECONDS:
            retry_seconds = _CACHE_TTL_SECONDS if _CAPITOL_TRADES_CACHE else CAPITOL_TRADES_FAILURE_RETRY_SECONDS
            if attempt_failures:
                parts = [
                    f"{urlparse(url).netloc}: {_summarize_request_error(err)}"
                    for url, err in attempt_failures
                ]
                failure_summary = "; ".join(parts)
            else:
                failure_summary = _summarize_request_error(e)
            if _CAPITOL_TRADES_CACHE:
                print(
                    f"Warning: Capitol Trades fetch failed [{failure_summary}]. "
                    f"Using cached Capitol data ({len(_CAPITOL_TRADES_CACHE)} records). "
                    f"Next fetch check in ~{int(retry_seconds)}s."
                )
            else:
                print(
                    f"Warning: Capitol Trades fetch failed [{failure_summary}] and no cache is available. "
                    f"Next retry in ~{int(retry_seconds)}s."
                )
            _LAST_WARNING_TS = now

        # Retry sooner when there is no cache; otherwise use normal cache cadence.
        if _CAPITOL_TRADES_CACHE:
            _LAST_FETCH_TS = now
        else:
            _LAST_FETCH_TS = now - max(0, (_CACHE_TTL_SECONDS - CAPITOL_TRADES_FAILURE_RETRY_SECONDS))
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


def fetch_stock_data(symbol, period="1y", start=None, end=None, use_cache=True, interval=None):
    """Fetch historical stock data using yfinance.

    Supports either a relative `period` (used by the live strategy) or explicit
    `start` / `end` dates (used by backtesting). Live requests are cached briefly
    to avoid repeated downloads for each symbol check.
    """
    cache_key = (str(symbol).upper(), period, start, end, interval)
    now = time.time()

    if use_cache and start is None and end is None:
        cached = _STOCK_DATA_CACHE.get(cache_key)
        if cached and now - cached[0] < STOCK_DATA_CACHE_TTL_SECONDS:
            return cached[1].copy()

    download_kwargs = {"progress": False}
    if interval:
        download_kwargs["interval"] = interval
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


# ---------------------------------------------------------------------------
# Global macro / sentiment data sources
# ---------------------------------------------------------------------------

_VIX_CACHE = None
_VIX_CACHE_TS = 0.0
_VIX_CACHE_TTL = 900  # 15 minutes

_NEWS_SENTIMENT_CACHE = {}
_NEWS_SENTIMENT_TS = {}
_NEWS_SENTIMENT_TTL = 1800  # 30 minutes

_GLOBAL_NEWS_CACHE = None
_GLOBAL_NEWS_CACHE_TS = 0.0
_GLOBAL_NEWS_CACHE_TTL = 1800  # 30 minutes

_SECTOR_CACHE = None
_SECTOR_CACHE_TS = 0.0
_SECTOR_CACHE_TTL = 1800  # 30 minutes
_EXTERNAL_RESEARCH_CACHE = None
_EXTERNAL_RESEARCH_CACHE_TS = 0.0

# Keywords that indicate positive or negative macro/tech/political sentiment
_POSITIVE_KEYWORDS = {
    "rally", "surge", "gain", "rise", "growth", "profit", "beat", "bullish",
    "upgrade", "breakthrough", "record", "strong", "approval", "deal", "ceasefire",
    "recovery", "innovation", "partnership", "expansion", "positive",
}
_NEGATIVE_KEYWORDS = {
    "crash", "plunge", "fall", "drop", "loss", "miss", "bearish", "downgrade",
    "tariff", "sanction", "ban", "war", "conflict", "recession", "inflation",
    "default", "scandal", "probe", "investigation", "negative", "fear", "risk",
    "tension", "sell-off", "downturn", "layoff", "bankruptcy",
}

_TOPIC_KEYWORDS = {
    "geopolitics": {
        "war", "conflict", "ceasefire", "sanction", "tariff", "tension", "election",
        "embassy", "nato", "china", "russia", "middle east",
    },
    "technology": {
        "ai", "chip", "semiconductor", "cloud", "software", "cyber", "data center",
        "automation", "quantum", "robotics",
    },
    "rates": {
        "fed", "fomc", "interest rate", "rate cut", "rate hike", "bond yield", "treasury",
    },
    "inflation": {
        "inflation", "cpi", "ppi", "price pressure", "cost pressure", "sticky prices",
    },
    "regulation": {
        "regulation", "antitrust", "lawsuit", "probe", "investigation", "fine", "sec",
        "doj", "ban", "policy",
    },
    "earnings": {
        "earnings", "guidance", "revenue", "eps", "forecast", "beat", "miss",
    },
    "supply_chain": {
        "supply chain", "shipping", "logistics", "factory", "shortage", "inventory",
    },
    "energy": {
        "oil", "gas", "opec", "crude", "lng", "pipeline", "refinery",
    },
    "commodities": {
        "commodity", "copper", "lithium", "uranium", "gold", "silver", "iron ore", "wheat",
    },
    "policy": {
        "policy", "government", "budget", "fiscal", "stimulus", "tax", "tariff", "subsidy",
    },
    "global_economy": {
        "gdp", "pmi", "unemployment", "consumer confidence", "debt", "trade deficit", "currency",
    },
    "market_movers": {
        "ceo", "federal reserve", "treasury secretary", "president", "minister", "central bank",
    },
}

_RSS_RESEARCH_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/news_301.rss",
    "https://www.investing.com/rss/news_95.rss",
]

_SEARCH_RESEARCH_QUERIES = [
    "global market policy changes stock market impact",
    "commodity price moves equities risk appetite",
    "emerging technology sectors investment outlook",
    "central bank policy market trend outlook",
]


def fetch_vix_level():
    """Return the latest VIX level (market fear index) via yfinance.

    Cached for 15 minutes. Returns a dict with 'vix' (float) and
    'fear_level' ('low' | 'moderate' | 'high' | 'extreme').
    Returns None on failure.
    """
    global _VIX_CACHE, _VIX_CACHE_TS
    now = time.time()
    if _VIX_CACHE and now - _VIX_CACHE_TS < _VIX_CACHE_TTL:
        return _VIX_CACHE

    try:
        data = yf.download("^VIX", period="5d", progress=False, auto_adjust=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        vix = float(data["Close"].iloc[-1])
        if vix < 15:
            fear = "low"
        elif vix < 20:
            fear = "moderate"
        elif vix < 30:
            fear = "high"
        else:
            fear = "extreme"
        _VIX_CACHE = {"vix": vix, "fear_level": fear}
        _VIX_CACHE_TS = now
        return _VIX_CACHE
    except Exception as e:
        print(f"VIX fetch failed: {e}")
        return None


def fetch_news_sentiment(symbol):
    """Score recent news headlines for a symbol using yfinance and keyword analysis.

    Returns a dict with:
    - 'score': aggregate sentiment score (positive = bullish, negative = bearish)
    - 'headline_count': number of headlines processed
    - 'headlines': recent headline titles
    - 'topic_scores': topic -> signed sentiment score
    Cached per symbol for 30 minutes.
    """
    global _NEWS_SENTIMENT_CACHE, _NEWS_SENTIMENT_TS
    symbol = symbol.upper()
    now = time.time()
    if symbol in _NEWS_SENTIMENT_CACHE and now - _NEWS_SENTIMENT_TS.get(symbol, 0) < _NEWS_SENTIMENT_TTL:
        return _NEWS_SENTIMENT_CACHE[symbol]

    try:
        ticker = yf.Ticker(symbol)
        news_items = ticker.news or []
        score = 0.0
        headlines = []
        topic_scores = {topic: 0.0 for topic in _TOPIC_KEYWORDS}
        for item in news_items[:15]:  # cap at 15 recent headlines
            title_raw = item.get("title", "")
            title = str(title_raw or "").strip()
            if not title:
                continue
            headlines.append(title)
            headline_score, topic_contrib = _score_headline(title)
            score += headline_score
            for topic, value in topic_contrib.items():
                topic_scores[topic] += value

        result = {
            "score": score,
            "headline_count": len(headlines),
            "headlines": headlines[:5],
            "topic_scores": topic_scores,
        }
        _NEWS_SENTIMENT_CACHE[symbol] = result
        _NEWS_SENTIMENT_TS[symbol] = now
        return result
    except Exception as e:
        print(f"News sentiment fetch failed for {symbol}: {e}")
        return {"score": 0, "headline_count": 0, "headlines": [], "topic_scores": {}}


def _score_headline(title):
    """Return (sentiment_score, topic_score_dict) for a single headline."""
    text = str(title or "").lower().strip()
    topic_scores = {topic: 0.0 for topic in _TOPIC_KEYWORDS}
    if not text:
        return 0.0, topic_scores

    pos = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
    neg = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)
    headline_score = float(pos - neg)

    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            topic_scores[topic] += headline_score

    return headline_score, topic_scores


def fetch_global_macro_sentiment():
    """Build macro/news sentiment from broad market and global proxies.

    Uses headline feeds from major indices, sector ETFs, and key commodities
    to capture global/local macro narrative shifts that may not appear in
    symbol-specific headlines.
    """
    global _GLOBAL_NEWS_CACHE, _GLOBAL_NEWS_CACHE_TS
    now = time.time()
    if _GLOBAL_NEWS_CACHE and now - _GLOBAL_NEWS_CACHE_TS < _GLOBAL_NEWS_CACHE_TTL:
        return _GLOBAL_NEWS_CACHE

    # Broad market + macro proxy universe.
    sources = ["^GSPC", "^IXIC", "^DJI", "XLK", "XLE", "XLF", "GC=F", "CL=F", "DX-Y.NYB"]
    topic_scores = {topic: 0.0 for topic in _TOPIC_KEYWORDS}
    score = 0.0
    headlines = []
    seen_titles = set()

    try:
        for source in sources:
            try:
                ticker = yf.Ticker(source)
                for item in (ticker.news or [])[:10]:
                    title = str(item.get("title", "") or "").strip()
                    if not title:
                        continue
                    dedupe_key = title.lower()
                    if dedupe_key in seen_titles:
                        continue
                    seen_titles.add(dedupe_key)
                    headlines.append(title)

                    headline_score, topic_contrib = _score_headline(title)
                    score += headline_score
                    for topic, value in topic_contrib.items():
                        topic_scores[topic] += value
            except Exception:
                continue

        _GLOBAL_NEWS_CACHE = {
            "score": score,
            "headline_count": len(headlines),
            "headlines": headlines[:10],
            "topic_scores": topic_scores,
        }
        _GLOBAL_NEWS_CACHE_TS = now
        return _GLOBAL_NEWS_CACHE
    except Exception as e:
        print(f"Global macro sentiment fetch failed: {e}")
        return {"score": 0.0, "headline_count": 0, "headlines": [], "topic_scores": {}}


def fetch_sector_momentum():
    """Return momentum scores for key sector ETFs to detect hot/cold sectors.

    Uses 5-day and 20-day returns on XLK (tech), XLE (energy), XLF (financials),
    XLV (healthcare), XLI (industrials), GLD (gold/defensive).
    Cached for 30 minutes. Returns a dict of symbol -> momentum_pct (5d).
    """
    global _SECTOR_CACHE, _SECTOR_CACHE_TS
    now = time.time()
    if _SECTOR_CACHE and now - _SECTOR_CACHE_TS < _SECTOR_CACHE_TTL:
        return _SECTOR_CACHE

    sectors = ["XLK", "XLE", "XLF", "XLV", "XLI", "GLD", "SPY"]
    result = {}
    try:
        for etf in sectors:
            try:
                data = yf.download(etf, period="1mo", progress=False, auto_adjust=False)
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                close = data["Close"].dropna()
                if len(close) >= 6:
                    mom_5d = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6])
                    mom_20d = float((close.iloc[-1] - close.iloc[0]) / close.iloc[0])
                    result[etf] = {"momentum_5d": mom_5d, "momentum_20d": mom_20d}
            except Exception:
                result[etf] = {"momentum_5d": 0.0, "momentum_20d": 0.0}

        _SECTOR_CACHE = result
        _SECTOR_CACHE_TS = now
        return result
    except Exception as e:
        print(f"Sector momentum fetch failed: {e}")
        return {}


def fetch_external_research_sentiment():
    """Fetch broader internet market research from RSS feeds.

    Captures policy, macro, technology, commodities, and market-mover narratives.
    Returns aggregate score + topic scores + sample headlines.
    """
    global _EXTERNAL_RESEARCH_CACHE, _EXTERNAL_RESEARCH_CACHE_TS
    if not EXTERNAL_RESEARCH_ENABLED:
        return {"score": 0.0, "headline_count": 0, "headlines": [], "topic_scores": {}}

    now = time.time()
    if _EXTERNAL_RESEARCH_CACHE and now - _EXTERNAL_RESEARCH_CACHE_TS < EXTERNAL_RESEARCH_CACHE_TTL_SECONDS:
        return _EXTERNAL_RESEARCH_CACHE

    topic_scores = {topic: 0.0 for topic in _TOPIC_KEYWORDS}
    score = 0.0
    headlines = []
    seen = set()
    source_hits = set()
    fresh_hits = 0
    total_hits = 0
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)

    for url in _RSS_RESEARCH_FEEDS:
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=_REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "xml")
            feed_has_hit = False
            for item in soup.find_all("item")[:12]:
                title = str((item.find("title").text if item.find("title") else "") or "").strip()
                desc = str((item.find("description").text if item.find("description") else "") or "").strip()
                pub_text = str((item.find("pubDate").text if item.find("pubDate") else "") or "").strip()
                headline = f"{title} {desc}".strip()
                if not headline:
                    continue
                key = headline.lower()
                if key in seen:
                    continue
                seen.add(key)
                total_hits += 1
                if pub_text:
                    try:
                        published = parsedate_to_datetime(pub_text)
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=timezone.utc)
                        if published >= fresh_cutoff:
                            fresh_hits += 1
                    except Exception:
                        pass
                hs, contrib = _score_headline(headline)
                score += hs
                for topic, value in contrib.items():
                    topic_scores[topic] += value
                if title:
                    headlines.append(title)
                feed_has_hit = True
            if feed_has_hit:
                source_hits.add(url)
        except Exception:
            continue

    search_payload = _fetch_search_engine_research()
    search_score = float(search_payload.get("score", 0.0))
    search_topics = search_payload.get("topic_scores", {}) or {}
    score += search_score
    for topic, val in search_topics.items():
        topic_scores[topic] = float(topic_scores.get(topic, 0.0)) + float(val)
    headlines.extend(search_payload.get("headlines", [])[:10])
    search_hits = int(search_payload.get("item_count", 0) or 0)
    total_hits += search_hits
    fresh_hits += int(search_payload.get("fresh_item_count", 0) or 0)
    if search_hits > 0:
        source_hits.add(f"search:{SEARCH_PROVIDER or 'unknown'}")

    source_count = len(source_hits)
    headline_count = len(headlines)
    fresh_ratio = (float(fresh_hits) / float(total_hits)) if total_hits > 0 else 0.0
    coverage_score = min(1.0, headline_count / max(1.0, float(EXTERNAL_RESEARCH_MIN_HEADLINES)))
    source_score = min(1.0, source_count / max(1.0, float(EXTERNAL_RESEARCH_MIN_SOURCES)))
    confidence = max(0.0, min(1.0, (0.5 * coverage_score) + (0.35 * source_score) + (0.15 * fresh_ratio)))
    reliable = bool(
        headline_count >= EXTERNAL_RESEARCH_MIN_HEADLINES
        and source_count >= EXTERNAL_RESEARCH_MIN_SOURCES
        and fresh_ratio >= EXTERNAL_RESEARCH_MIN_FRESH_RATIO
    )

    _EXTERNAL_RESEARCH_CACHE = {
        "score": score,
        "headline_count": headline_count,
        "headlines": headlines[:14],
        "topic_scores": topic_scores,
        "search_provider": SEARCH_PROVIDER or "disabled",
        "search_enabled": bool(SEARCH_PROVIDER and SEARCH_API_KEY),
        "source_count": source_count,
        "fresh_item_count": fresh_hits,
        "fresh_ratio": fresh_ratio,
        "confidence": confidence,
        "reliable": reliable,
    }
    _EXTERNAL_RESEARCH_CACHE_TS = now
    return _EXTERNAL_RESEARCH_CACHE


def _fetch_search_engine_research():
    if not SEARCH_PROVIDER or not SEARCH_API_KEY:
        return {"score": 0.0, "headlines": [], "topic_scores": {}}

    if SEARCH_PROVIDER == "brave":
        return _search_brave()
    if SEARCH_PROVIDER == "serpapi":
        return _search_serpapi()
    return {"score": 0.0, "headlines": [], "topic_scores": {}}


def _score_search_items(items):
    topic_scores = {topic: 0.0 for topic in _TOPIC_KEYWORDS}
    score = 0.0
    headlines = []
    seen = set()
    fresh_count = 0
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    for item in items:
        if isinstance(item, dict):
            text = str(item.get("text", "") or "").strip()
            ts = item.get("published_ts")
        else:
            text = str(item or "").strip()
            ts = None
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if ts:
            try:
                published = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                if published >= fresh_cutoff:
                    fresh_count += 1
            except Exception:
                pass
        s, contrib = _score_headline(text)
        score += s
        for topic, val in contrib.items():
            topic_scores[topic] = float(topic_scores.get(topic, 0.0)) + float(val)
        headlines.append(text[:180])
    return {
        "score": score,
        "headlines": headlines[:20],
        "topic_scores": topic_scores,
        "item_count": len(headlines),
        "fresh_item_count": fresh_count,
    }


def _search_brave():
    items = []
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": SEARCH_API_KEY,
    }
    for q in _SEARCH_RESEARCH_QUERIES:
        try:
            r = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": q, "count": 8},
                headers=headers,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            payload = r.json()
            for row in (payload.get("web", {}) or {}).get("results", [])[:8]:
                title = str(row.get("title", "") or "")
                desc = str(row.get("description", "") or "")
                items.append({"text": f"{title} {desc}".strip(), "published_ts": row.get("age")})
        except Exception:
            continue
    return _score_search_items(items)


def _search_serpapi():
    items = []
    for q in _SEARCH_RESEARCH_QUERIES:
        try:
            r = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": SEARCH_ENGINE or "google",
                    "q": q,
                    "api_key": SEARCH_API_KEY,
                    "num": 8,
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            payload = r.json()
            for row in payload.get("organic_results", [])[:8]:
                title = str(row.get("title", "") or "")
                snippet = str(row.get("snippet", "") or "")
                date_text = str(row.get("date", "") or "").strip()
                ts = None
                if date_text:
                    try:
                        parsed = parsedate_to_datetime(date_text)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        ts = parsed.timestamp()
                    except Exception:
                        ts = None
                items.append({"text": f"{title} {snippet}".strip(), "published_ts": ts})
        except Exception:
            continue
    return _score_search_items(items)