from datetime import UTC, datetime
import json
import os
import re
import subprocess
import time
from urllib.parse import parse_qs
from collections import Counter

import yfinance as yf

from shared.regime_detector import detect_equity_regime, detect_crypto_regime

from app.routes import ROUTES
from app.utils.helpers import error_response, json_response

PYTHON_BIN = "/home/codespace/.python/current/bin/python"

_BOT_CONFIG = {
    "trading_bot": {
        "session": "trading_bot",
        "cwd": "/workspaces/Capitol_Trades_API/trading_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./supervise_bot.sh",
        "log": "/workspaces/Capitol_Trades_API/trading_bot/bot.log",
    },
    "crypto_bot": {
        "session": "crypto_bot",
        "cwd": "/workspaces/Capitol_Trades_API/crypto_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./supervise_bot.sh",
        "log": "/workspaces/Capitol_Trades_API/crypto_bot/bot.log",
    },
    "asx_bot": {
        "session": "asx_bot",
        "cwd": "/workspaces/Capitol_Trades_API/asx_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./run_tmux.sh",
        "log": "/workspaces/Capitol_Trades_API/asx_bot/output.log",
    },
    "forex_bot": {
        "session": "forex_bot",
        "cwd": "/workspaces/Capitol_Trades_API/forex_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./run_tmux.sh",
        "log": "/workspaces/Capitol_Trades_API/forex_bot/output.log",
    },
    "tech_research_bot": {
        "session": "tech_research_bot",
        "cwd": "/workspaces/Capitol_Trades_API/tech_research_bot",
        "cmd": f"PYTHON_BIN={PYTHON_BIN} bash ./supervise_bot.sh",
        "log": "/workspaces/Capitol_Trades_API/tech_research_bot/bot.log",
    },
}

_TRADING_TRADE_LOG = "/workspaces/Capitol_Trades_API/trading_bot/logs/trade_log.csv"
_TRADING_EQUITY_LOG = "/workspaces/Capitol_Trades_API/trading_bot/logs/equity_log.csv"
_CRYPTO_TRADE_LOG = "/workspaces/Capitol_Trades_API/crypto_bot/logs/trade_log.csv"
_ASX_STATE_FILE = "/workspaces/Capitol_Trades_API/asx_bot/paper_state.json"
_ASX_TRADE_LOG = "/workspaces/Capitol_Trades_API/asx_bot/logs/trades_log.csv"
_TECH_RESEARCH_SNAPSHOT_FILE = "/workspaces/Capitol_Trades_API/tech_research_bot/output/latest_research.json"
_AUTONOMY_STATE_FILES = {
    "trading_bot": "/workspaces/Capitol_Trades_API/trading_bot/models/autonomy_state.json",
    "crypto_bot": "/workspaces/Capitol_Trades_API/crypto_bot/models/autonomy_state.json",
    "asx_bot": "/workspaces/Capitol_Trades_API/asx_bot/models/autonomy_state.json",
    "forex_bot": "/workspaces/Capitol_Trades_API/forex_bot/models/autonomy_state.json",
}

_AUTONOMY_THRESHOLDS = {
    "trading_bot": {
        "closed_trades_7d": 8,
        "win_rate_7d": 0.52,
        "profit_factor_7d": 1.10,
        "realized_pnl_7d": 0.0,
        "max_drawdown_7d": 0.06,
    },
    "crypto_bot": {
        "closed_trades_7d": 8,
        "win_rate_7d": 0.52,
        "profit_factor_7d": 1.10,
        "realized_pnl_7d": 0.0,
        "max_drawdown_7d": 0.08,
    },
    "asx_bot": {
        "closed_trades_7d": 8,
        "win_rate_7d": 0.52,
        "profit_factor_7d": 1.10,
        "realized_pnl_7d": 0.0,
        "max_drawdown_7d": 0.08,
    },
    "forex_bot": {
        "closed_trades_7d": 8,
        "win_rate_7d": 0.52,
        "profit_factor_7d": 1.10,
        "realized_pnl_7d": 0.0,
        "max_drawdown_7d": 0.08,
    },
}

_REGIME_CACHE = {}
_REGIME_CACHE_TTL_SECONDS = 300


def _read_json_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _read_csv_rows(path, max_rows=500):
    if not os.path.exists(path):
        return []
    try:
        import csv
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if max_rows and len(rows) > max_rows:
            return rows[-max_rows:]
        return rows
    except Exception:
        return []


def _f(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _live_regime_snapshot(bot_id):
    now = time.time()
    cached = _REGIME_CACHE.get(bot_id)
    if cached and (now - float(cached.get("ts", 0.0))) < _REGIME_CACHE_TTL_SECONDS:
        return dict(cached.get("value") or {})

    result = {
        "label": "n/a",
        "confidence": None,
    }

    try:
        if bot_id == "trading_bot":
            env = _read_bot_env("trading_bot")
            symbol = str(env.get("MARKET_REGIME_SYMBOL") or "SPY").strip().upper()
            sw = int(_f(env.get("MARKET_REGIME_SHORT_WINDOW"), 50))
            lw = int(_f(env.get("MARKET_REGIME_LONG_WINDOW"), 200))
            data = yf.download(symbol, period="1y", progress=False, auto_adjust=False)
            if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
                data.columns = data.columns.get_level_values(0)
            close = data["Close"] if "Close" in data else None
            if close is not None and len(close) >= 30:
                reg = detect_equity_regime(close, short_window=sw, long_window=lw)
                result = {
                    "label": str(reg.get("label") or "unknown"),
                    "confidence": _f(reg.get("confidence"), 0.0),
                }

        elif bot_id == "crypto_bot":
            env = _read_bot_env("crypto_bot")
            watchlist = str(env.get("CRYPTO_WATCHLIST") or "BTC/USD")
            first = watchlist.split(",", 1)[0].strip().upper() or "BTC/USD"
            ticker = first.replace("/", "-")
            data = yf.download(ticker, period="180d", progress=False, auto_adjust=False)
            if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
                data.columns = data.columns.get_level_values(0)
            close = data["Close"] if "Close" in data else None
            if close is not None and len(close) >= 30:
                reg = detect_crypto_regime(close)
                result = {
                    "label": str(reg.get("label") or "unknown"),
                    "confidence": _f(reg.get("confidence"), 0.0),
                }
    except Exception:
        result = {
            "label": "unknown",
            "confidence": None,
        }

    _REGIME_CACHE[bot_id] = {
        "ts": now,
        "value": result,
    }
    return dict(result)


def _read_bot_env(bot_id):
    cfg = _BOT_CONFIG.get(bot_id) or {}
    cwd = cfg.get("cwd") or ""
    env_path = os.path.join(cwd, ".env") if cwd else ""
    values = {}
    if not env_path or not os.path.exists(env_path):
        return values
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except Exception:
        return {}
    return values


def _extract_line_timestamp(line):
    if not line:
        return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", line)
    return m.group(1) if m else ""


def _extract_bot_heartbeat(bot_id, lines):
    signal_line = ""
    mode_line = ""
    cycle_line = ""

    for line in reversed(lines or []):
        if (not signal_line) and re.search(r":\s*(BUY|SELL|HOLD)\s*\|", line, flags=re.IGNORECASE):
            signal_line = line
        if (not mode_line) and "Autonomy profile:" in line:
            mode_line = line
        if (not cycle_line) and (
            "Portfolio snapshot" in line
            or "Waiting " in line
            or "Sleeping " in line
            or re.search(r"\bCycle\b", line)
        ):
            cycle_line = line
        if signal_line and mode_line and cycle_line:
            break

    signal = ""
    if signal_line:
        m = re.search(r":\s*(BUY|SELL|HOLD)\s*\|", signal_line, flags=re.IGNORECASE)
        if m:
            signal = m.group(1).upper()

    ts = _extract_line_timestamp(signal_line) or _extract_line_timestamp(mode_line) or _extract_line_timestamp(cycle_line)

    log_path = (_BOT_CONFIG.get(bot_id) or {}).get("log")
    log_mtime = ""
    if log_path and os.path.exists(log_path):
        try:
            log_mtime = datetime.fromtimestamp(os.path.getmtime(log_path), UTC).isoformat()
        except Exception:
            log_mtime = ""

    return {
        "last_signal": signal,
        "last_signal_line": signal_line,
        "last_mode_line": mode_line,
        "last_cycle_line": cycle_line,
        "last_seen": ts or log_mtime,
        "log_mtime": log_mtime,
    }


def _is_research_line(line):
    up = (line or "").upper()
    if not up:
        return False
    if "EXT=" in up:
        return True
    tokens = (
        "LEARNED INFLUENCE REPORT",
        "EXTERNAL RESEARCH",
        "SEARCH_PROVIDER",
        "SEARCH_ENGINE",
        "RESEARCH",
        "SENTIMENT",
        "GEOPOLITICS",
        "TECHNOLOGY",
        "COMMODITIES",
        "MACRO",
    )
    return any(tok in up for tok in tokens)


def _summarize_research_activity(bot_id, n=320):
    log_path = (_BOT_CONFIG.get(bot_id) or {}).get("log")
    lines = _last_log_lines(log_path, n=n) if log_path else []
    research_lines = [ln for ln in lines if _is_research_line(ln)]

    ext_values = []
    for ln in research_lines:
        for token in re.findall(r"(?:^|\s)(?:EXT|ext)=([+-]?\d+(?:\.\d+)?)", ln):
            try:
                ext_values.append(float(token))
            except Exception:
                continue

    env = _read_bot_env(bot_id)
    provider = (env.get("SEARCH_PROVIDER") or "").strip().lower()
    engine = (env.get("SEARCH_ENGINE") or "").strip().lower()
    key = (env.get("SEARCH_API_KEY") or env.get("SERPAPI_API_KEY") or "").strip()
    enabled = (env.get("EXTERNAL_RESEARCH_ENABLED") or "true").strip().lower() == "true"

    latest_line = research_lines[-1] if research_lines else ""
    return {
        "provider": provider or "-",
        "engine": engine or "-",
        "enabled": enabled,
        "key_set": bool(key),
        "mentions": len(research_lines),
        "nonzero_ext_mentions": sum(1 for v in ext_values if abs(v) > 1e-9),
        "last_seen": _extract_line_timestamp(latest_line),
        "latest_line": latest_line,
        "recent_lines": research_lines[-8:],
    }


def _summarize_research_force_buy(lines):
    matches = []
    for line in lines or []:
        if "research_force_buy" not in line:
            continue

        prob = None
        impact = None
        evidence = None

        m_prob = re.search(r"p=([0-9]+(?:\.[0-9]+)?)%", line)
        if m_prob:
            try:
                prob = float(m_prob.group(1)) / 100.0
            except Exception:
                prob = None

        m_impact = re.search(r"impact=([+-]?[0-9]+(?:\.[0-9]+)?)", line)
        if m_impact:
            try:
                impact = float(m_impact.group(1))
            except Exception:
                impact = None

        m_evidence = re.search(r"evidence=(\d+)", line)
        if m_evidence:
            try:
                evidence = int(m_evidence.group(1))
            except Exception:
                evidence = None

        matches.append({
            "line": line,
            "timestamp": _extract_line_timestamp(line),
            "probability": prob,
            "impact_score": impact,
            "evidence_count": evidence,
        })

    latest = matches[-1] if matches else {}
    return {
        "trigger_count_recent": len(matches),
        "triggered_recently": bool(matches),
        "last_seen": latest.get("timestamp") or "",
        "last_probability": latest.get("probability"),
        "last_impact_score": latest.get("impact_score"),
        "last_evidence_count": latest.get("evidence_count"),
        "last_line": latest.get("line") or "",
        "recent": matches[-6:],
    }


def _summarize_trading_bot():
    trades = _read_csv_rows(_TRADING_TRADE_LOG, max_rows=2000)
    equity = _read_csv_rows(_TRADING_EQUITY_LOG, max_rows=2000)
    lines = _last_log_lines(_BOT_CONFIG["trading_bot"]["log"], n=260)

    buy_count = sum(1 for r in trades if str(r.get("action", "")).upper() == "BUY")
    sell_count = sum(1 for r in trades if str(r.get("action", "")).upper() == "SELL")
    realized_pnl = sum(_f(r.get("notional"), 0.0) * 0 for r in [])

    # Use note-level pnl if present in note text, otherwise keep 0 as conservative.
    for r in trades:
        if str(r.get("action", "")).upper() != "SELL":
            continue
        note = str(r.get("note", ""))
        if "pnl=" in note.lower():
            try:
                token = note.lower().split("pnl=", 1)[1].split()[0].replace(",", "")
                realized_pnl += float(token)
            except Exception:
                pass

    latest_equity = _f(equity[-1].get("portfolio_value"), 0.0) if equity else 0.0
    latest_cash = _f(equity[-1].get("cash_balance"), 0.0) if equity else 0.0
    open_positions = int(_f(equity[-1].get("open_positions"), 0.0)) if equity else 0

    symbol_counts = Counter(str(r.get("symbol", "")).upper() for r in trades if r.get("symbol"))
    top_symbols = [{"symbol": s, "count": c} for s, c in symbol_counts.most_common(5)]

    return {
        "trade_rows": len(trades),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "realized_pnl_estimate": round(realized_pnl, 2),
        "latest_equity": round(latest_equity, 2),
        "latest_cash": round(latest_cash, 2),
        "open_positions": open_positions,
        "top_symbols": top_symbols,
        "recent_trades": trades[-12:],
        "heartbeat": _extract_bot_heartbeat("trading_bot", lines),
        "research": _summarize_research_activity("trading_bot"),
        "research_force_buy": _summarize_research_force_buy(lines),
    }


def _summarize_crypto_bot():
    lines = _last_log_lines(_BOT_CONFIG["crypto_bot"]["log"], n=220)
    joined = "\n".join(lines)
    buy_hits = sum(1 for l in lines if "BUY" in l.upper())
    sell_hits = sum(1 for l in lines if "SELL" in l.upper())
    hold_hits = sum(1 for l in lines if "HOLD" in l.upper())
    pairs = Counter()
    for l in lines:
        up = l.upper()
        for p in ("BTC/USD", "ETH/USD", "SOL/USD"):
            if p in up:
                pairs[p] += 1

    regime_line = ""
    notes_line = ""
    for l in reversed(lines):
        if not regime_line and "Research regime:" in l:
            regime_line = l
        if not notes_line and "Research strategy notes:" in l:
            notes_line = l
        if regime_line and notes_line:
            break

    weighted_score = None
    provider = "-"
    headlines = 0
    topics = []

    if regime_line:
        m_score = re.search(r"score=([+-]?\d+(?:\.\d+)?)", regime_line)
        if m_score:
            weighted_score = _to_float_or_none(m_score.group(1))

        m_provider = re.search(r"provider=([^\s]+)", regime_line)
        if m_provider:
            provider = (m_provider.group(1) or "-").strip().lower()

        m_headlines = re.search(r"headlines=(\d+)", regime_line)
        if m_headlines:
            try:
                headlines = int(m_headlines.group(1))
            except Exception:
                headlines = 0

        m_topics = re.search(r"topics=([^\n\r]+)$", regime_line)
        if m_topics:
            topics = [x.strip() for x in str(m_topics.group(1)).split(",") if x.strip() and x.strip().lower() != "none"]

    strategy_notes = notes_line.split("Research strategy notes:", 1)[-1].strip() if notes_line else ""

    return {
        "recent_log_lines": lines[-30:],
        "signal_mentions": {
            "buy": buy_hits,
            "sell": sell_hits,
            "hold": hold_hits,
        },
        "pair_mentions": [{"pair": p, "count": c} for p, c in pairs.most_common()],
        "has_error": "ERROR" in joined.upper() or "TRACEBACK" in joined.upper(),
        "heartbeat": _extract_bot_heartbeat("crypto_bot", lines),
        "research": _summarize_research_activity("crypto_bot"),
        "crypto_research": {
            "weighted_score": weighted_score,
            "provider": provider,
            "headlines": headlines,
            "dominant_topics": topics,
            "strategy_notes": strategy_notes,
            "regime_line": regime_line,
        },
    }


def _summarize_asx_bot():
    trades = _read_csv_rows(_ASX_TRADE_LOG, max_rows=2000)
    lines = _last_log_lines(_BOT_CONFIG["asx_bot"]["log"], n=260)
    state = {}
    if os.path.exists(_ASX_STATE_FILE):
        try:
            with open(_ASX_STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    cash = _f(state.get("cash"), 0.0)
    positions = state.get("positions") or {}
    open_positions = len([k for k, v in positions.items() if _f((v or {}).get("qty"), 0.0) > 0])

    buy_count = sum(1 for r in trades if str(r.get("action", "")).upper() == "BUY")
    sell_count = sum(1 for r in trades if str(r.get("action", "")).upper() == "SELL")
    realized_pnl = sum(_f(r.get("pnl"), 0.0) for r in trades if str(r.get("action", "")).upper() == "SELL")
    latest_equity = _f(trades[-1].get("portfolio_value"), 0.0) if trades else cash

    symbol_counts = Counter(str(r.get("symbol", "")).upper() for r in trades if r.get("symbol"))
    top_symbols = [{"symbol": s, "count": c} for s, c in symbol_counts.most_common(5)]

    return {
        "trade_rows": len(trades),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "realized_pnl": round(realized_pnl, 2),
        "latest_equity": round(latest_equity, 2),
        "latest_cash": round(cash, 2),
        "open_positions": open_positions,
        "top_symbols": top_symbols,
        "recent_trades": trades[-12:],
        "heartbeat": _extract_bot_heartbeat("asx_bot", lines),
        "research": _summarize_research_activity("asx_bot"),
    }


def _summarize_forex_bot():
    lines = _last_log_lines(_BOT_CONFIG["forex_bot"]["log"], n=260)
    joined = "\n".join(lines)
    buy_hits = sum(1 for l in lines if "BUY" in l.upper())
    sell_hits = sum(1 for l in lines if "SELL" in l.upper())
    hold_hits = sum(1 for l in lines if "HOLD" in l.upper())

    pairs = Counter()
    known_pairs = ("EUR/USD", "GBP/USD", "AUD/USD", "USD/JPY", "USD/CAD", "NZD/USD", "USD/CHF")
    for l in lines:
        up = l.upper()
        for p in known_pairs:
            if p in up:
                pairs[p] += 1

    latest_portfolio_line = ""
    for l in reversed(lines):
        if "PORTFOLIO VALUE" in l.upper() or "STARTING BALANCE" in l.upper():
            latest_portfolio_line = l
            break

    return {
        "recent_log_lines": lines[-30:],
        "signal_mentions": {
            "buy": buy_hits,
            "sell": sell_hits,
            "hold": hold_hits,
        },
        "pair_mentions": [{"pair": p, "count": c} for p, c in pairs.most_common()],
        "latest_portfolio_line": latest_portfolio_line,
        "has_error": "ERROR" in joined.upper() or "TRACEBACK" in joined.upper(),
        "heartbeat": _extract_bot_heartbeat("forex_bot", lines),
        "research": _summarize_research_activity("forex_bot"),
    }


def _summarize_tech_research_bot():
    lines = _last_log_lines(_BOT_CONFIG["tech_research_bot"]["log"], n=260)
    snapshot = {}
    if os.path.exists(_TECH_RESEARCH_SNAPSHOT_FILE):
        try:
            with open(_TECH_RESEARCH_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                snapshot = loaded
        except Exception:
            snapshot = {}

    top_candidates = snapshot.get("top_candidates") or []
    if not isinstance(top_candidates, list):
        top_candidates = []

    theme_counts = Counter(str(x.get("theme") or "unknown") for x in top_candidates if isinstance(x, dict))
    top_themes = [{"theme": t, "count": c} for t, c in theme_counts.most_common(6)]

    avg_probability = _to_float_or_none(snapshot.get("avg_probability"))
    min_probability_threshold = _to_float_or_none(snapshot.get("min_probability_threshold"))
    candidate_count = int(snapshot.get("candidate_count") or len(top_candidates) or 0)

    return {
        "candidate_count": candidate_count,
        "avg_probability": round(avg_probability, 4) if avg_probability is not None else None,
        "min_probability_threshold": round(min_probability_threshold, 4) if min_probability_threshold is not None else None,
        "generated_at": str(snapshot.get("generated_at") or ""),
        "methodology": str(snapshot.get("methodology") or ""),
        "top_themes": top_themes,
        "top_candidates": top_candidates[:20],
        "recent_log_lines": lines[-40:],
        "heartbeat": _extract_bot_heartbeat("tech_research_bot", lines),
        "research": _summarize_research_activity("tech_research_bot"),
    }


def _estimate_open_cost_basis(trades):
    positions = {}
    for row in trades:
        action = str(row.get("action") or "").upper()
        symbol = str(row.get("symbol") or "").upper().strip()
        qty = _f(row.get("qty"), 0.0)
        price = _f(row.get("price"), 0.0)
        if not symbol or qty <= 0 or price <= 0:
            continue

        pos = positions.setdefault(symbol, {"qty": 0.0, "cost": 0.0})
        if action == "BUY":
            pos["qty"] += qty
            pos["cost"] += qty * price
        elif action == "SELL" and pos["qty"] > 0:
            sell_qty = min(qty, pos["qty"])
            avg_cost = (pos["cost"] / pos["qty"]) if pos["qty"] > 0 else 0.0
            pos["qty"] -= sell_qty
            pos["cost"] -= avg_cost * sell_qty
            if pos["qty"] <= 1e-9:
                pos["qty"] = 0.0
                pos["cost"] = 0.0

    return round(sum(max(0.0, p["cost"]) for p in positions.values()), 2)


def _parse_iso_ts(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _build_projection_returns(portfolio_series):
    horizons = [5, 10, 15, 20, 25, 30]
    anchor_annual_return = 0.10
    max_projection_return = 0.25
    min_projection_return = -0.15
    if not portfolio_series:
        return {
            "horizons": [{"years": y, "projected_value": 0.0, "projected_return_pct": 0.0} for y in horizons],
            "base_liquidated_value": 0.0,
            "annualized_return": 0.0,
            "window_days": 0.0,
            "assumptions": "Insufficient portfolio history for projection.",
        }

    start_v = _f(portfolio_series[0].get("v"), 0.0)
    end_v = _f(portfolio_series[-1].get("v"), 0.0)
    start_ts = _parse_iso_ts(portfolio_series[0].get("t"))
    end_ts = _parse_iso_ts(portfolio_series[-1].get("t"))

    if start_v <= 0 or end_v <= 0 or not start_ts or not end_ts:
        return {
            "horizons": [{
                "years": y,
                "projected_value": round(max(0.0, end_v), 2),
                "projected_return_pct": 0.0,
                "projected_delta_value": 0.0,
            } for y in horizons],
            "base_liquidated_value": round(max(0.0, end_v), 2),
            "annualized_return": 0.0,
            "window_days": 0.0,
            "assumptions": "Projection uses flat growth because valid baseline history was not available.",
        }

    delta_days = max(1.0, (end_ts - start_ts).total_seconds() / 86400.0)
    observed_years = max(1.0 / 365.25, delta_days / 365.25)
    gross = end_v / start_v
    raw_annualized = (gross ** (1.0 / observed_years)) - 1.0 if gross > 0 else 0.0
    clamped_raw = max(min_projection_return, min(max_projection_return, raw_annualized))

    # Reliability-weighted blend:
    # short windows lean toward a conservative long-run anchor,
    # then converge to observed behavior as history approaches 1 year.
    reliability = max(0.0, min(1.0, delta_days / 365.25))
    annualized = (reliability * clamped_raw) + ((1.0 - reliability) * anchor_annual_return)
    annualized = max(min_projection_return, min(max_projection_return, annualized))

    points = []
    for years in horizons:
        projected_value = max(0.0, end_v * ((1.0 + annualized) ** years))
        projected_return_pct = ((projected_value / end_v) - 1.0) * 100.0 if end_v > 0 else 0.0
        projected_delta_value = projected_value - end_v
        points.append({
            "years": years,
            "projected_value": round(projected_value, 2),
            "projected_return_pct": round(projected_return_pct, 2),
            "projected_delta_value": round(projected_delta_value, 2),
        })

    return {
        "horizons": points,
        "base_liquidated_value": round(end_v, 2),
        "annualized_return": round(annualized, 6),
        "raw_annualized_return": round(raw_annualized, 6),
        "reliability": round(reliability, 4),
        "window_days": round(delta_days, 1),
        "assumptions": "Projection blends observed annualized return with a 10% anchor until enough history accumulates, then compounds with clamp [-15%, +25%].",
    }


def _build_investment_progress(max_points=240):
    trading_rows = _read_csv_rows(_TRADING_TRADE_LOG, max_rows=4000)
    equity_rows = _read_csv_rows(_TRADING_EQUITY_LOG, max_rows=4000)
    crypto_rows = _read_csv_rows(_CRYPTO_TRADE_LOG, max_rows=4000)

    if max_points and len(equity_rows) > max_points:
        equity_rows = equity_rows[-max_points:]

    portfolio = []
    cash = []
    for row in equity_rows:
        ts = str(row.get("timestamp") or "").strip()
        if not ts:
            continue
        portfolio.append({
            "t": ts,
            "v": round(_f(row.get("portfolio_value"), 0.0), 2),
        })
        cash.append({
            "t": ts,
            "v": round(_f(row.get("cash_balance"), 0.0), 2),
        })

    crypto_pnl = []
    running_pnl = 0.0
    for row in crypto_rows:
        action = str(row.get("action") or "").upper()
        if action != "SELL":
            continue
        pnl = _to_float_or_none(row.get("pnl"))
        if pnl is None:
            note = str(row.get("note") or "")
            if "pnl=" in note.lower():
                try:
                    token = note.lower().split("pnl=", 1)[1].split()[0].replace(",", "")
                    pnl = float(token)
                except Exception:
                    pnl = 0.0
            else:
                pnl = 0.0
        running_pnl += float(pnl)
        ts = str(row.get("exit_time") or row.get("timestamp") or "").strip()
        if ts:
            crypto_pnl.append({"t": ts, "v": round(running_pnl, 2)})

    if max_points and len(crypto_pnl) > max_points:
        crypto_pnl = crypto_pnl[-max_points:]

    latest_portfolio = portfolio[-1]["v"] if portfolio else 0.0
    latest_cash = cash[-1]["v"] if cash else 0.0
    latest_crypto_pnl = crypto_pnl[-1]["v"] if crypto_pnl else 0.0
    start_portfolio = portfolio[0]["v"] if portfolio else 0.0
    net_change = latest_portfolio - start_portfolio if portfolio else 0.0
    pct_change = (net_change / start_portfolio * 100.0) if start_portfolio > 0 else 0.0
    invested_capital = max(0.0, latest_portfolio - latest_cash)

    trading_realized = 0.0
    for row in trading_rows:
        if str(row.get("action") or "").upper() != "SELL":
            continue
        note = str(row.get("note") or "")
        if "pnl=" not in note.lower():
            continue
        try:
            token = note.lower().split("pnl=", 1)[1].split()[0].replace(",", "")
            trading_realized += float(token)
        except Exception:
            continue

    open_cost_basis = _estimate_open_cost_basis(trading_rows)
    unrealized_pnl = invested_capital - open_cost_basis
    net_if_liquidated = trading_realized + unrealized_pnl
    combined_realized = trading_realized + latest_crypto_pnl
    projection = _build_projection_returns(portfolio)

    return {
        "portfolio": portfolio,
        "cash": cash,
        "crypto_pnl": crypto_pnl,
        "projection": projection,
        "latest": {
            "portfolio_value": round(latest_portfolio, 2),
            "cash_balance": round(latest_cash, 2),
            "crypto_cum_realized_pnl": round(latest_crypto_pnl, 2),
            "window_net_change": round(net_change, 2),
            "window_pct_change": round(pct_change, 2),
            "invested_capital": round(invested_capital, 2),
            "estimated_open_cost_basis": round(open_cost_basis, 2),
            "estimated_unrealized_pnl": round(unrealized_pnl, 2),
            "estimated_trading_realized_pnl": round(trading_realized, 2),
            "estimated_net_pnl_if_liquidated": round(net_if_liquidated, 2),
            "estimated_combined_realized_pnl": round(combined_realized, 2),
        },
    }


def _strategy_reference(bot_id):
    if bot_id == "trading_bot":
        return {
            "summary": "LSTM model + event/news impact learner + adaptive experience policy + autonomous execution gate",
            "rules": [
                "Model prediction edge and confidence gating",
                "Event impact adjustment from learned topic effects",
                "Adaptive policy from realized outcomes",
                "Autonomous performance gate (profit factor/win rate/drawdown) controls new entries and risk sizing",
                "External internet research sentiment (policy/macro/technology/commodities) informs experimentation",
                "Risk controls: stop-loss, take-profit, max positions, cooldown",
            ],
        }
    if bot_id == "crypto_bot":
        return {
            "summary": "Rules-based crypto strategy using EMA trend + RSI + risk constraints",
            "rules": [
                "Fast/slow EMA direction filter",
                "RSI oversold / take-profit checks",
                "Position sizing and stop loss controls",
                "Paper-only execution guard",
            ],
        }
    if bot_id == "asx_bot":
        return {
            "summary": "LSTM + VWAP/EMA/RSI/volume confluence with event-impact learner",
            "rules": [
                "Predicted next-close edge thresholding",
                "VWAP value-zone and EMA trend confirmation",
                "RSI and Bollinger guard rails",
                "Event-impact edge adjustment with bounded effect",
                "Risk controls with stop, target, cooldown, max positions",
            ],
        }
    if bot_id == "forex_bot":
        return {
            "summary": "LSTM-assisted FX signals with trend filters and conservative risk sizing",
            "rules": [
                "Per-pair predictive signal analysis",
                "EMA/RSI/ATR-informed execution",
                "Trade cooldown and max concurrent positions",
                "Paper-trading validation before live deployment",
            ],
        }
    if bot_id == "tech_research_bot":
        return {
            "summary": "Emerging-technology intelligence bot with impact-probability scoring and ranked candidate output",
            "rules": [
                "Aggregates major tech RSS + targeted Google News query feeds",
                "Deduplicates and scores headlines with weighted tech-impact keywords",
                "Penalizes low-quality/suspicious terms and normalizes to probability",
                "Ranks highest probability significant-impact themes for operator review",
            ],
        }
    return {
        "summary": "Combined bot view",
        "rules": [],
    }


def _to_float_or_none(value):
    if value in (None, "", "none", "None"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _extract_autonomy_keyvals(line):
    payload = line.split("Autonomy profile:", 1)[-1]
    found = {}
    for key, value in re.findall(r"([a-zA-Z0-9_]+)=([^\s|]+)", payload):
        found[key] = value.strip()
    return found


def _parse_blocked(raw):
    token = (raw or "").strip()
    if not token or token.lower() == "none":
        return []
    return [x.strip().upper() for x in token.split(",") if x.strip()]


def _autonomy_improvement_snapshot(lines):
    updates = []
    for line in lines:
        if "Auto-improvement:" in line:
            msg = line.split("Auto-improvement:", 1)[-1].strip()
            # Some logs include a duplicated prefix from caller + callee.
            if msg.startswith("Auto-improvement:"):
                msg = msg.split("Auto-improvement:", 1)[-1].strip()
            updates.append({
                "line": line,
                "message": msg,
                "timestamp": _extract_line_timestamp(line),
            })

    latest = updates[-1] if updates else {}
    top_allocations = ""
    blocked_list = ""
    for item in reversed(updates):
        msg = item.get("message") or ""
        if (not top_allocations) and msg.lower().startswith("top allocations:"):
            top_allocations = msg.split(":", 1)[-1].strip()
        if (not blocked_list) and msg.lower().startswith("underperformer cap/block list:"):
            blocked_list = msg.split(":", 1)[-1].strip()
        if top_allocations and blocked_list:
            break

    return {
        "updates": updates[-8:],
        "last_message": latest.get("message") or "",
        "last_seen": latest.get("timestamp") or "",
        "top_allocations": top_allocations,
        "blocked_list": blocked_list,
    }


def _autonomy_learning_state(bot_id):
    state_path = _AUTONOMY_STATE_FILES.get(bot_id)
    if not state_path or not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    mode_stats = raw.get("mode_stats") or {}

    def normalize(mode):
        item = mode_stats.get(mode) or {}
        wins = int(item.get("wins", 0) or 0)
        losses = int(item.get("losses", 0) or 0)
        total = wins + losses
        return {
            "wins": wins,
            "losses": losses,
            "total": total,
            "success_rate": (wins / total) if total else None,
            "pnl_sum": _to_float_or_none(item.get("pnl_sum")),
        }

    return {
        "last_mode": raw.get("last_mode") or "",
        "last_realized_pnl_7d": _to_float_or_none(raw.get("last_realized_pnl_7d")),
        "last_drawdown_7d": _to_float_or_none(raw.get("last_drawdown_7d")),
        "aggressive_cooldown_until": raw.get("aggressive_cooldown_until") or "",
        "mode_stats": {
            "aggressive": normalize("aggressive"),
            "normal": normalize("normal"),
            "cautious": normalize("cautious"),
            "capital_preservation": normalize("capital_preservation"),
        },
    }


def _autonomy_snapshot_from_log(bot_id):
    # Trading bot emits dense retraining logs (many epoch lines), which can push
    # autonomy headers out of a short tail window.
    tail_window = 3000 if bot_id == "trading_bot" else 800
    lines = _last_log_lines(_BOT_CONFIG[bot_id]["log"], n=tail_window)
    improvement = _autonomy_improvement_snapshot(lines)
    autonomy_line = ""
    for line in reversed(lines):
        if "Autonomy profile:" in line:
            autonomy_line = line
            break

    if not autonomy_line:
        fallback_mode = "unknown"
        for line in reversed(lines):
            marker = "| autonomy="
            if marker in line:
                tail = line.split(marker, 1)[-1].strip()
                fallback_mode = (tail.split()[0] if tail else "unknown") or "unknown"
                break
        return {
            "mode": fallback_mode,
            "score": None,
            "allow_entries": None,
            "risk_mult": None,
            "blocked_symbols": [],
            "metrics": {},
            "checks": {},
            "pass_count": 0,
            "total_checks": 0,
            "improvement": improvement,
            "learning": _autonomy_learning_state(bot_id),
        }

    kv = _extract_autonomy_keyvals(autonomy_line)
    metrics = {
        "closed_trades_7d": _to_float_or_none(kv.get("closed_7d")),
        "win_rate_7d": _to_float_or_none((kv.get("win_7d") or "").replace("%", "")),
        "profit_factor_7d": _to_float_or_none(kv.get("pf_7d")),
        "realized_pnl_7d": _to_float_or_none(kv.get("pnl_7d")),
        "max_drawdown_7d": _to_float_or_none((kv.get("dd_7d") or "").replace("%", "")),
    }

    # win_7d and dd_7d are printed as percentages, convert to ratio.
    if metrics["win_rate_7d"] is not None:
        metrics["win_rate_7d"] /= 100.0
    if metrics["max_drawdown_7d"] is not None:
        metrics["max_drawdown_7d"] /= 100.0

    thresholds = _AUTONOMY_THRESHOLDS.get(bot_id, {})
    checks = {}

    def add_check(name, comparator="ge"):
        target = thresholds.get(name)
        value = metrics.get(name)
        if target is None or value is None:
            checks[name] = {
                "value": value,
                "target": target,
                "pass": None,
            }
            return
        if comparator == "le":
            passed = value <= target
        else:
            passed = value >= target
        checks[name] = {
            "value": value,
            "target": target,
            "pass": passed,
        }

    add_check("closed_trades_7d", comparator="ge")
    add_check("win_rate_7d", comparator="ge")
    add_check("profit_factor_7d", comparator="ge")
    add_check("realized_pnl_7d", comparator="ge")
    add_check("max_drawdown_7d", comparator="le")

    pass_values = [v.get("pass") for v in checks.values() if v.get("pass") is not None]
    pass_count = sum(1 for x in pass_values if x)

    return {
        "mode": kv.get("mode") or "unknown",
        "score": _to_float_or_none(kv.get("score")),
        "allow_entries": (kv.get("allow_entries") or "").lower() == "true" if kv.get("allow_entries") is not None else None,
        "risk_mult": _to_float_or_none(kv.get("risk_mult")),
        "blocked_symbols": _parse_blocked(kv.get("blocked")),
        "metrics": metrics,
        "checks": checks,
        "pass_count": pass_count,
        "total_checks": len(pass_values),
        "improvement": improvement,
        "learning": _autonomy_learning_state(bot_id),
    }


def _autonomy_dashboard_payload():
    bots = {}
    for bot_id in ("trading_bot", "crypto_bot", "asx_bot", "forex_bot"):
        snap = _autonomy_snapshot_from_log(bot_id)
        snap["regime"] = _live_regime_snapshot(bot_id)
        bots[bot_id] = snap
    return {
        "bots": bots,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _build_returns_coach_response(bot_id, strategy_summary, snapshot_lines, weakness_lines, actions, kpis):
    lines = [
        f"{bot_id} returns coach summary:",
        f"- Strategy: {strategy_summary}",
        "- Current snapshot:",
    ]
    lines.extend([f"  • {x}" for x in snapshot_lines])

    if weakness_lines:
        lines.append("- What is likely limiting returns right now:")
        lines.extend([f"  • {x}" for x in weakness_lines])

    lines.append("- Highest-impact learning actions (next cycle):")
    lines.extend([f"  {i+1}. {a}" for i, a in enumerate(actions)])

    lines.append("- Track these KPIs to confirm improvement:")
    lines.extend([f"  • {k}" for k in kpis])

    lines.append("- Risk guardrail: increase size only after KPI improvement is stable for multiple cycles.")
    lines.append("")
    lines.extend(_seven_day_experiment_plan(bot_id, kpis))
    return "\n".join(lines)


def _seven_day_experiment_plan(bot_id, kpis=None):
    kpis = kpis or []

    if bot_id == "trading_bot":
        thresholds = [
            "Profit factor improves by >= 10% vs prior 7 days (minimum target: 1.15)",
            "Realized PnL per closed trade is positive and >= 5% better vs prior week",
            "Max drawdown does not worsen; target <= prior week drawdown",
        ]
    elif bot_id == "crypto_bot":
        thresholds = [
            "Realized PnL per completed trade improves by >= 10% vs prior 7 days",
            "BUY-to-SELL conversion ratio >= 0.70 without higher error count",
            "Per-pair max drawdown stays flat or improves vs prior week",
        ]
    elif bot_id == "asx_bot":
        thresholds = [
            "Profit factor on closed trades >= 1.10 and improving vs prior week",
            "Average realized PnL per close improves by >= 8% vs prior 7 days",
            "Win rate does not fall by more than 2 percentage points while improving returns",
        ]
    elif bot_id == "forex_bot":
        thresholds = [
            "Average expectancy per active pair is positive for the week",
            "Win rate in best trading session improves by >= 5 percentage points",
            "Trade frequency does not rise faster than net PnL (avoid overtrading)",
        ]
    else:
        thresholds = [
            "Portfolio-level realized PnL improves by >= 8% vs prior 7 days",
            "Aggregate max drawdown does not worsen vs prior week",
            "Error count remains flat or lower while returns improve",
        ]

    lines = [
        "- 7-day experiment plan (required):",
        "  1. Keep current baseline for 24h and record KPI baseline values.",
        "  2. Apply one change only (single-variable test) for days 2-6.",
        "  3. Compare day-7 metrics against baseline and decide pass/fail.",
        "- Pass/Fail thresholds:",
    ]
    lines.extend([f"  • {t}" for t in thresholds])

    if kpis:
        lines.append("- KPI scoreboard for this run:")
        lines.extend([f"  • {k}" for k in kpis])

    lines.append("- Decision rule: if fewer than 2 threshold checks pass, revert change and test a new hypothesis.")
    return lines


def _is_autonomous_request(q):
    return any(k in q for k in (
        "autonomous",
        "think for itself",
        "think for iteself",
        "decide for me",
        "make decisions",
        "decision mode",
        "autopilot",
    ))


def _autopilot_level(score):
    if score >= 35:
        return "DEPLOY", "high"
    if score >= 20:
        return "LIMITED_DEPLOY", "medium"
    return "HOLD_OR_REDUCE", "low"


def _autonomous_response(bot_id, objective, score, snapshot_lines, reasons, actions, kill_switch):
    decision, confidence = _autopilot_level(score)
    lines = [
        f"AUTOPILOT DECISION - {bot_id}",
        f"- Objective: {objective}",
        f"- Decision now: {decision}",
        f"- Confidence: {confidence} (score={score})",
        "- Decision inputs:",
    ]
    lines.extend([f"  • {x}" for x in snapshot_lines])
    lines.append("- Why this decision:")
    lines.extend([f"  • {x}" for x in reasons])
    lines.append("- Execute this now (next 24h):")
    lines.extend([f"  {i+1}. {x}" for i, x in enumerate(actions)])
    lines.append(f"- Kill-switch: {kill_switch}")
    lines.append("")
    lines.extend(_seven_day_experiment_plan(bot_id, []))
    return "\n".join(lines)


def _is_human_report_request(q):
    return any(k in q for k in (
        "report",
        "performance",
        "how is",
        "how are",
        "findings",
        "research",
        "improve",
        "improvement",
        "suggest",
        "recommend",
        "summary",
    ))


def _fmt_money(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "-"


def _fmt_pct(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "-"


def _research_takeaway(research):
    mentions = int(research.get("mentions") or 0)
    nonzero = int(research.get("nonzero_ext_mentions") or 0)
    provider = str(research.get("provider") or "-")
    enabled = bool(research.get("enabled"))
    key_set = bool(research.get("key_set"))
    latest = str(research.get("latest_line") or "").strip()

    if not enabled:
        return "Research is disabled, so the bot is currently running on internal signal logic only."
    if not key_set:
        return f"Research is configured via {provider}, but API key is not active, so external findings are limited."
    if mentions == 0:
        return "Research is enabled but no recent research hits were logged in the latest window."
    if nonzero == 0:
        return "Research is flowing, but it is mostly neutral right now (external score near zero)."
    if latest:
        return f"Research is active with directional influence. Latest notable line: {latest}"
    return "Research is active and contributing to decision context."


def _human_report_crypto(status, crypto):
    r = (crypto.get("research") or {})
    cr = (crypto.get("crypto_research") or {})
    buys = int((crypto.get("signal_mentions") or {}).get("buy") or 0)
    sells = int((crypto.get("signal_mentions") or {}).get("sell") or 0)
    holds = int((crypto.get("signal_mentions") or {}).get("hold") or 0)
    conversion = (sells / buys) if buys > 0 else 0.0
    pair_text = ", ".join([f"{x['pair']} ({x['count']})" for x in (crypto.get("pair_mentions") or [])[:5]]) or "none"
    weighted = cr.get("weighted_score")
    weighted_text = "-" if weighted is None else f"{float(weighted):.2f}"
    topics = ", ".join((cr.get("dominant_topics") or [])[:4]) or "none"
    notes = str(cr.get("strategy_notes") or "none")

    suggestions = []
    if buys > 0 and sells == 0:
        suggestions.append("Improve exit conversion by tightening take-profit/exit logic in low-momentum windows.")
    if holds > (buys + sells):
        suggestions.append("Reduce HOLD saturation by enabling entries only when both momentum and research regime agree.")
    if bool(crypto.get("has_error")):
        suggestions.append("Fix runtime errors first; unstable execution will dominate strategy quality.")
    if not suggestions:
        suggestions.append("Keep position sizing conservative and scale only when BUY-to-SELL conversion and realized expectancy both improve.")

    return (
        "Crypto bot update:\n"
        f"- Status: {'running' if status['crypto_bot']['running'] else 'stopped'}\n"
        f"- Signal mix: BUY={buys}, SELL={sells}, HOLD={holds} (BUY->SELL conversion {conversion:.2f})\n"
        f"- Active pairs: {pair_text}\n"
        f"- Research score: {weighted_text}, topics: {topics}, headlines: {int(cr.get('headlines') or 0)}\n"
        f"- Research takeaway: {_research_takeaway(r)}\n"
        f"- Strategy finding: {notes}\n"
        "- Suggested improvements:\n"
        + "\n".join([f"  {i+1}. {x}" for i, x in enumerate(suggestions)])
    )


def _human_report_trading(status, trading):
    r = (trading.get("research") or {})
    buys = int(trading.get("buy_count") or 0)
    sells = int(trading.get("sell_count") or 0)
    conversion = (sells / buys) if buys > 0 else 0.0
    tops = ", ".join([f"{x['symbol']} ({x['count']})" for x in (trading.get("top_symbols") or [])[:5]]) or "none"

    suggestions = []
    if sells == 0 and buys > 0:
        suggestions.append("Increase exit discipline so open positions convert into realized feedback faster.")
    if int(trading.get("open_positions") or 0) > 8:
        suggestions.append("Concentrate on fewer high-edge symbols to avoid diluted performance.")
    if not suggestions:
        suggestions.append("Continue ranking symbols by realized expectancy and reallocate toward top performers weekly.")

    return (
        "Trading bot update:\n"
        f"- Status: {'running' if status['trading_bot']['running'] else 'stopped'}\n"
        f"- Equity: {_fmt_money(trading.get('latest_equity'))}, cash: {_fmt_money(trading.get('latest_cash'))}, open positions: {int(trading.get('open_positions') or 0)}\n"
        f"- Trade flow: BUY={buys}, SELL={sells}, conversion={conversion:.2f}, estimated realized PnL={_fmt_money(trading.get('realized_pnl_estimate'))}\n"
        f"- Most active symbols: {tops}\n"
        f"- Research takeaway: {_research_takeaway(r)}\n"
        "- Suggested improvements:\n"
        + "\n".join([f"  {i+1}. {x}" for i, x in enumerate(suggestions)])
    )


def _human_report_asx(status, asx):
    r = (asx.get("research") or {})
    buys = int(asx.get("buy_count") or 0)
    sells = int(asx.get("sell_count") or 0)
    conversion = (sells / buys) if buys > 0 else 0.0
    tops = ", ".join([f"{x['symbol']} ({x['count']})" for x in (asx.get("top_symbols") or [])[:5]]) or "none"

    return (
        "ASX bot update:\n"
        f"- Status: {'running' if status['asx_bot']['running'] else 'stopped'}\n"
        f"- Equity: {_fmt_money(asx.get('latest_equity'))}, cash: {_fmt_money(asx.get('latest_cash'))}, open positions: {int(asx.get('open_positions') or 0)}\n"
        f"- Trade flow: BUY={buys}, SELL={sells}, conversion={conversion:.2f}, realized PnL={_fmt_money(asx.get('realized_pnl'))}\n"
        f"- Most active symbols: {tops}\n"
        f"- Research takeaway: {_research_takeaway(r)}\n"
        "- Suggested improvements:\n"
        "  1. Prune weak symbols by realized expectancy and keep capital on top ASX names.\n"
        "  2. Raise minimum edge slightly and compare win rate/profit factor after 30 closes.\n"
        "  3. Keep risk flat unless both win rate and realized PnL improve together."
    )


def _human_report_forex(status, forex):
    r = (forex.get("research") or {})
    signals = forex.get("signal_mentions") or {}
    buys = int(signals.get("buy") or 0)
    sells = int(signals.get("sell") or 0)
    holds = int(signals.get("hold") or 0)
    pair_text = ", ".join([f"{x['pair']} ({x['count']})" for x in (forex.get("pair_mentions") or [])[:6]]) or "none"

    return (
        "Forex bot update:\n"
        f"- Status: {'running' if status['forex_bot']['running'] else 'stopped'}\n"
        f"- Signal mix: BUY={buys}, SELL={sells}, HOLD={holds}\n"
        f"- Pairs observed: {pair_text}\n"
        f"- Portfolio note: {forex.get('latest_portfolio_line') or 'not found'}\n"
        f"- Research takeaway: {_research_takeaway(r)}\n"
        "- Suggested improvements:\n"
        "  1. Keep only positive-expectancy pairs active.\n"
        "  2. Add session filtering and reduce exposure in weak sessions.\n"
        "  3. Increase cooldown for whipsaw pairs to reduce noise trades."
    )


def _safe_ratio(num, den):
    try:
        den_f = float(den)
        if den_f == 0:
            return 0.0
        return float(num) / den_f
    except Exception:
        return 0.0


def _error_in_status_log(status_entry):
    lines = (status_entry or {}).get("log") or []
    joined = "\n".join(lines).upper()
    return ("ERROR" in joined) or ("TRACEBACK" in joined)


def _build_allocation_plan(status, trading, crypto, asx, forex):
    auto = _autonomy_dashboard_payload().get("bots", {})

    bots = {
        "trading_bot": {
            "running": bool((status.get("trading_bot") or {}).get("running")),
            "has_error": _error_in_status_log(status.get("trading_bot")),
            "expectancy_proxy": _safe_ratio(float(trading.get("realized_pnl_estimate") or 0.0), max(1, int(trading.get("sell_count") or 0))),
            "sell_count": int(trading.get("sell_count") or 0),
        },
        "crypto_bot": {
            "running": bool((status.get("crypto_bot") or {}).get("running")),
            "has_error": bool(crypto.get("has_error")),
            "expectancy_proxy": _safe_ratio(int((crypto.get("signal_mentions") or {}).get("sell") or 0), max(1, int((crypto.get("signal_mentions") or {}).get("buy") or 0))),
            "sell_count": int((crypto.get("signal_mentions") or {}).get("sell") or 0),
        },
        "asx_bot": {
            "running": bool((status.get("asx_bot") or {}).get("running")),
            "has_error": _error_in_status_log(status.get("asx_bot")),
            "expectancy_proxy": _safe_ratio(float(asx.get("realized_pnl") or 0.0), max(1, int(asx.get("sell_count") or 0))),
            "sell_count": int(asx.get("sell_count") or 0),
        },
        "forex_bot": {
            "running": bool((status.get("forex_bot") or {}).get("running")),
            "has_error": bool(forex.get("has_error")),
            "expectancy_proxy": _safe_ratio(int((forex.get("signal_mentions") or {}).get("sell") or 0), max(1, int((forex.get("signal_mentions") or {}).get("buy") or 0))),
            "sell_count": int((forex.get("signal_mentions") or {}).get("sell") or 0),
        },
    }

    raw_scores = {}
    reasons = {}
    for bot_id, d in bots.items():
        s = 0.0
        r = []
        if d["running"]:
            s += 2.0
            r.append("running")
        else:
            r.append("stopped")
        if d["has_error"]:
            s -= 2.0
            r.append("errors detected")
        else:
            s += 1.0
            r.append("clean runtime")

        snap = auto.get(bot_id) or {}
        pass_count = int(snap.get("pass_count") or 0)
        total_checks = int(snap.get("total_checks") or 0)
        check_ratio = _safe_ratio(pass_count, total_checks)
        s += (check_ratio * 4.0)
        r.append(f"checks {pass_count}/{total_checks}")

        exp = float(d.get("expectancy_proxy") or 0.0)
        if exp > 0:
            s += min(2.5, exp / 100.0)
            r.append("positive expectancy proxy")
        elif exp < 0:
            s -= min(2.5, abs(exp) / 100.0)
            r.append("negative expectancy proxy")

        if d.get("sell_count", 0) <= 0:
            s -= 0.5
            r.append("low close feedback")

        raw_scores[bot_id] = max(0.0, s)
        reasons[bot_id] = r

    running_bots = [b for b, d in bots.items() if d["running"]]
    if not running_bots:
        return {
            "weights": {b: 0 for b in bots},
            "notes": ["No bots are running, so allocation is paused."],
            "reasons": reasons,
        }

    # Start from proportional scores with a small floor for active bots.
    floor = 5
    weight_pool = 100 - (floor * len(running_bots))
    score_sum = sum(raw_scores[b] for b in running_bots)
    weights = {b: 0 for b in bots}
    for b in running_bots:
        if score_sum > 0:
            weights[b] = floor + int(round(weight_pool * (raw_scores[b] / score_sum)))
        else:
            weights[b] = floor + int(round(weight_pool / len(running_bots)))

    # Normalize to exactly 100 for running bots.
    running_total = sum(weights[b] for b in running_bots)
    diff = 100 - running_total
    if running_bots and diff != 0:
        best = max(running_bots, key=lambda b: raw_scores[b])
        weights[best] = max(0, weights[best] + diff)

    # Underperformer cap: if failed checks or errors, cap at 10%.
    for b in running_bots:
        snap = auto.get(b) or {}
        pass_count = int(snap.get("pass_count") or 0)
        total_checks = int(snap.get("total_checks") or 0)
        failed_gate = (total_checks > 0 and pass_count < 2) or bots[b]["has_error"]
        if failed_gate and weights[b] > 10:
            excess = weights[b] - 10
            weights[b] = 10
            elig = [x for x in running_bots if x != b and not bots[x]["has_error"]]
            if elig:
                bonus = int(excess / len(elig))
                rem = excess - (bonus * len(elig))
                for x in elig:
                    weights[x] += bonus
                if rem > 0:
                    best = max(elig, key=lambda x: raw_scores[x])
                    weights[best] += rem

    notes = [
        "Rotation rule: increase allocation toward highest score bots with clean runtime and stronger expectancy.",
        "Underperformer rule: cap allocation at 10% when a bot fails threshold checks or shows runtime errors.",
        "Re-evaluation rule: recompute this allocation once per day using return-per-risk and threshold pass rate.",
    ]
    return {
        "weights": weights,
        "notes": notes,
        "reasons": reasons,
    }


def _human_report_combined(status, trading, crypto, asx, forex):
    running_count = sum(1 for b in ("trading_bot", "crypto_bot", "asx_bot", "forex_bot") if status[b]["running"])
    trade_pnl = float(trading.get("realized_pnl_estimate") or 0.0)
    asx_pnl = float(asx.get("realized_pnl") or 0.0)
    crypto_mix = crypto.get("signal_mentions") or {}
    fx_mix = forex.get("signal_mentions") or {}
    alloc = _build_allocation_plan(status, trading, crypto, asx, forex)
    weights = alloc.get("weights") or {}
    allocation_lines = [
        f"  • trading_bot: {int(weights.get('trading_bot', 0))}%",
        f"  • crypto_bot: {int(weights.get('crypto_bot', 0))}%",
        f"  • asx_bot: {int(weights.get('asx_bot', 0))}%",
        f"  • forex_bot: {int(weights.get('forex_bot', 0))}%",
    ]

    return (
        "Portfolio summary across all bots:\n"
        f"- Bots running: {running_count}/4\n"
        f"- Trading bot estimated realized PnL: {_fmt_money(trade_pnl)}\n"
        f"- ASX bot realized PnL: {_fmt_money(asx_pnl)}\n"
        f"- Crypto signal mix: BUY={int(crypto_mix.get('buy') or 0)}, SELL={int(crypto_mix.get('sell') or 0)}, HOLD={int(crypto_mix.get('hold') or 0)}\n"
        f"- Forex signal mix: BUY={int(fx_mix.get('buy') or 0)}, SELL={int(fx_mix.get('sell') or 0)}, HOLD={int(fx_mix.get('hold') or 0)}\n"
        f"- Research findings: trading({_research_takeaway(trading.get('research') or {})}) | crypto({_research_takeaway(crypto.get('research') or {})}) | asx({_research_takeaway(asx.get('research') or {})}) | forex({_research_takeaway(forex.get('research') or {})})\n"
        "- Proposed daily allocation (return-per-risk weighted):\n"
        + "\n".join(allocation_lines)
        + "\n"
        + "- Execution policy:\n"
        + "\n".join([f"  {i+1}. {x}" for i, x in enumerate(alloc.get("notes") or [])])
    )


def _bot_copilot_answer(bot_id, message):
    q = (message or "").strip().lower()
    status = _check_bot_status()
    trading = _summarize_trading_bot()
    crypto = _summarize_crypto_bot()
    autonomous_mode = _is_autonomous_request(q)
    human_report_mode = _is_human_report_request(q)

    if bot_id == "tech_research_bot":
        tech = _summarize_tech_research_bot()
        top = tech.get("top_candidates") or []
        if not top:
            return (
                "Tech research bot update:\n"
                "- No ranked candidates yet.\n"
                "- Wait for the next research cycle or check tech_research_bot logs."
            )

        top_lines = []
        for i, item in enumerate(top[:8], start=1):
            prob = _to_float_or_none(item.get("probability_significant_impact"))
            impact = _to_float_or_none(item.get("impact_score"))
            theme = str(item.get("theme") or "unknown")
            title = str(item.get("title") or "").strip()
            prob_txt = f"{(prob * 100):.1f}%" if prob is not None else "-"
            impact_txt = f"{impact:.2f}" if impact is not None else "-"
            top_lines.append(f"  {i}. p={prob_txt}, impact={impact_txt}, theme={theme} :: {title}")

        avg_prob = _to_float_or_none(tech.get("avg_probability"))
        threshold = _to_float_or_none(tech.get("min_probability_threshold"))
        themes = ", ".join([f"{x['theme']} ({x['count']})" for x in (tech.get("top_themes") or [])[:5]]) or "none"

        return (
            "Tech research bot update:\n"
            f"- Generated at: {tech.get('generated_at') or '-'}\n"
            f"- Ranked candidates: {int(tech.get('candidate_count') or 0)}\n"
            f"- Avg probability: {((avg_prob or 0.0) * 100):.1f}%\n"
            f"- Minimum probability threshold: {((threshold or 0.0) * 100):.1f}%\n"
            f"- Top themes: {themes}\n"
            "- Highest-impact emerging technologies right now:\n"
            + "\n".join(top_lines)
        )

    if bot_id == "crypto_bot":
        strategy = _strategy_reference("crypto_bot")
        if human_report_mode and not autonomous_mode:
            return _human_report_crypto(status, crypto)
        if autonomous_mode:
            buys = crypto["signal_mentions"]["buy"]
            sells = crypto["signal_mentions"]["sell"]
            holds = crypto["signal_mentions"]["hold"]
            score = 0
            if status["crypto_bot"]["running"]:
                score += 15
            if buys > 0:
                score += 8
            if sells > 0:
                score += 8
            if buys > 0 and sells == 0:
                score -= 10
            if holds > (buys + sells):
                score -= 6
            if crypto["has_error"]:
                score -= 12
            pair_text = ", ".join([x["pair"] + " (" + str(x["count"]) + ")" for x in crypto["pair_mentions"]]) or "none"
            return _autonomous_response(
                "crypto_bot",
                "maximize risk-adjusted returns using only strongest crypto regimes",
                score,
                [
                    f"Signals: BUY={buys}, SELL={sells}, HOLD={holds}",
                    f"Pairs active: {pair_text}",
                    f"Bot status: {'running' if status['crypto_bot']['running'] else 'stopped'}",
                    f"Log health: {'errors detected' if crypto['has_error'] else 'clean'}",
                ],
                [
                    "Recent signal mix determines whether entries are converting into exits.",
                    "High HOLD share usually means weak edge or thresholds too strict.",
                    "Any runtime errors reduce execution quality and should lower deployment confidence.",
                ],
                [
                    "Concentrate allocation on top 1-2 pairs by realized expectancy and pause weakest pair.",
                    "Run one threshold change only (EMA/RSI) and compare BUY->SELL conversion over next 24h.",
                    "If conversion improves with stable drawdown, step size up one level; otherwise revert.",
                ],
                "Stop new entries immediately if error count rises or per-pair drawdown exceeds prior-week max.",
            )
        if any(k in q for k in ("learn", "learning", "strategy", "signal", "improv", "return")):
            buys = crypto["signal_mentions"]["buy"]
            sells = crypto["signal_mentions"]["sell"]
            holds = crypto["signal_mentions"]["hold"]
            pair_text = ", ".join([x["pair"] + " (" + str(x["count"]) + ")" for x in crypto["pair_mentions"]]) or "none"
            weaknesses = []
            if buys > 0 and sells == 0:
                weaknesses.append("entries appear to outnumber exits, which can trap capital")
            if holds > (buys + sells):
                weaknesses.append("high HOLD share may indicate thresholds are too strict for current regime")
            if crypto["has_error"]:
                weaknesses.append("errors in recent logs can reduce signal quality and execution consistency")

            return _build_returns_coach_response(
                "crypto_bot",
                strategy["summary"],
                [
                    f"Signal mentions: BUY={buys}, SELL={sells}, HOLD={holds}",
                    f"Most active pairs: {pair_text}",
                    f"Health: {'issues detected' if crypto['has_error'] else 'no obvious runtime errors'}",
                ],
                weaknesses,
                [
                    "Run a 7-day pair-by-pair scorecard: realized PnL per BUY signal, max adverse excursion, and hold duration.",
                    "Tune EMA/RSI thresholds on the weakest pair first, then re-check BUY->SELL conversion rate before wider rollout.",
                    "Add a volatility regime split (trending vs choppy hours) and disable entries in the weaker regime.",
                ],
                [
                    "BUY-to-SELL conversion ratio",
                    "Realized PnL per completed trade",
                    "Max drawdown per pair",
                    "Error count per 24h",
                ],
            )
        return (
            "Ask about crypto learning, strategy signals, or return improvement focus."
            + "\n\n"
            + "\n".join(_seven_day_experiment_plan("crypto_bot", []))
        )

    if bot_id == "asx_bot":
        asx = _summarize_asx_bot()
        strategy = _strategy_reference("asx_bot")
        if human_report_mode and not autonomous_mode:
            return _human_report_asx(status, asx)
        if autonomous_mode:
            score = 0
            if status["asx_bot"]["running"]:
                score += 15
            if asx["realized_pnl"] > 0:
                score += 12
            else:
                score -= 8
            if asx["sell_count"] > 0:
                score += 8
            if asx["trade_rows"] >= 20:
                score += 8
            else:
                score -= 5
            if asx["open_positions"] > 6:
                score -= 5
            tops = ", ".join([f"{x['symbol']} ({x['count']})" for x in asx['top_symbols']]) or "none"
            return _autonomous_response(
                "asx_bot",
                "maximize high-conviction ASX returns while pruning low-edge symbols",
                score,
                [
                    f"Trades: {asx['trade_rows']} (BUY={asx['buy_count']}, SELL={asx['sell_count']})",
                    f"Realized PnL: ${asx['realized_pnl']:,.2f}",
                    f"Open positions: {asx['open_positions']}",
                    f"Top symbols: {tops}",
                ],
                [
                    "Positive realized PnL and sufficient closes indicate usable feedback for adaptation.",
                    "Low sample size or too many open positions usually weakens decision quality.",
                    "Symbol concentration should favor recent expectancy leaders.",
                ],
                [
                    "Drop bottom-quartile symbols by realized PnL per close for this cycle.",
                    "Increase edge threshold one notch and observe profit factor impact over next 30 closes.",
                    "Only expand exposure if win rate and average PnL/close improve together.",
                ],
                "Reduce exposure if profit factor drops below 1.0 or open-position count expands without PnL improvement.",
            )
        if any(k in q for k in ("learn", "learning", "strategy", "signal", "improv", "return", "performance", "pnl")):
            tops = ", ".join([f"{x['symbol']} ({x['count']})" for x in asx['top_symbols']]) or "none yet"
            weaknesses = []
            if asx["sell_count"] == 0 and asx["buy_count"] > 0:
                weaknesses.append("few or no closes means weak feedback loop for learning")
            if asx["trade_rows"] < 20:
                weaknesses.append("sample size is still small, so edge estimates can be noisy")
            return _build_returns_coach_response(
                "asx_bot",
                strategy["summary"],
                [
                    f"Trades logged: {asx['trade_rows']} (BUY={asx['buy_count']}, SELL={asx['sell_count']})",
                    f"Latest equity: ${asx['latest_equity']:,.2f}, cash ${asx['latest_cash']:,.2f}, open positions {asx['open_positions']}",
                    f"Realized PnL: ${asx['realized_pnl']:,.2f}",
                    f"Most active symbols: {tops}",
                ],
                weaknesses,
                [
                    "Rank symbols by realized PnL per trade and temporarily drop the bottom quartile from the watchlist.",
                    "Raise the minimum effective predicted edge slightly and compare win rate / profit factor over the next 30 closes.",
                    "Run a weekly review of event-impact topic weights; cap or decay topics with persistent negative contribution.",
                ],
                [
                    "Profit factor on closed ASX trades",
                    "Win rate after edge-threshold change",
                    "Average realized PnL per close",
                    "Open-position holding time before exit",
                ],
            )
        return (
            "Ask about ASX learning, strategy rules, equity/PnL, or top traded symbols."
            + "\n\n"
            + "\n".join(_seven_day_experiment_plan("asx_bot", []))
        )

    if bot_id == "forex_bot":
        forex = _summarize_forex_bot()
        strategy = _strategy_reference("forex_bot")
        if human_report_mode and not autonomous_mode:
            return _human_report_forex(status, forex)
        if autonomous_mode:
            buys = forex["signal_mentions"]["buy"]
            sells = forex["signal_mentions"]["sell"]
            holds = forex["signal_mentions"]["hold"]
            score = 0
            if status["forex_bot"]["running"]:
                score += 15
            if buys + sells > 0:
                score += 10
            else:
                score -= 8
            if sells > 0:
                score += 6
            if holds > (buys + sells):
                score -= 6
            if forex["has_error"]:
                score -= 12
            pair_text = ", ".join([x["pair"] + " (" + str(x["count"]) + ")" for x in forex["pair_mentions"]]) or "none"
            return _autonomous_response(
                "forex_bot",
                "maximize FX returns by session and pair-level expectancy",
                score,
                [
                    f"Signals: BUY={buys}, SELL={sells}, HOLD={holds}",
                    f"Observed pairs: {pair_text}",
                    f"Portfolio note: {forex['latest_portfolio_line'] or 'not found'}",
                    f"Log health: {'errors detected' if forex['has_error'] else 'clean'}",
                ],
                [
                    "Trade activity and exit frequency are required for feedback-driven optimization.",
                    "High HOLD share often signals weak market regime fit.",
                    "Log/runtime issues reduce confidence in autonomous deployment.",
                ],
                [
                    "Enable session filter and deploy only in the highest expectancy session first.",
                    "Pause pairs with negative expectancy and reallocate to strongest pair cluster.",
                    "Scale only after expectancy and drawdown both improve for two consecutive cycles.",
                ],
                "Pause entries if session win rate drops below prior-week baseline or drawdown accelerates.",
            )
        if any(k in q for k in ("learn", "learning", "strategy", "signal", "improv", "return", "performance", "pnl")):
            pair_text = ", ".join([x["pair"] + " (" + str(x["count"]) + ")" for x in forex["pair_mentions"]]) or "none"
            weaknesses = []
            if forex["signal_mentions"]["buy"] == 0 and forex["signal_mentions"]["sell"] == 0:
                weaknesses.append("very low trade activity limits learning speed")
            if forex["has_error"]:
                weaknesses.append("runtime/log errors may be degrading execution quality")
            return _build_returns_coach_response(
                "forex_bot",
                strategy["summary"],
                [
                    f"Signal mentions: BUY={forex['signal_mentions']['buy']}, SELL={forex['signal_mentions']['sell']}, HOLD={forex['signal_mentions']['hold']}",
                    f"Most observed pairs: {pair_text}",
                    f"Latest portfolio note: {forex['latest_portfolio_line'] or 'not found'}",
                    f"Health: {'issues detected' if forex['has_error'] else 'no obvious runtime errors'}",
                ],
                weaknesses,
                [
                    "Measure per-pair expectancy (avg win * win rate - avg loss * loss rate) and keep only positive-expectancy pairs.",
                    "Add session filtering (Asia/London/NY overlap) and compare signal quality by session before scaling.",
                    "Increase cooldown for pairs with repeated whipsaws and re-evaluate trade frequency vs expectancy.",
                ],
                [
                    "Expectancy per pair",
                    "Win rate by session",
                    "Average adverse excursion",
                    "Trade frequency vs net PnL",
                ],
            )
        return (
            "Ask about forex learning, strategy signals, pair behavior, or return improvement focus."
            + "\n\n"
            + "\n".join(_seven_day_experiment_plan("forex_bot", []))
        )

    if bot_id == "trading_bot":
        strategy = _strategy_reference("trading_bot")
        if human_report_mode and not autonomous_mode:
            return _human_report_trading(status, trading)
        if autonomous_mode:
            score = 0
            if status["trading_bot"]["running"]:
                score += 15
            if trading["realized_pnl_estimate"] > 0:
                score += 12
            else:
                score -= 8
            if trading["sell_count"] > 0:
                score += 8
            if trading["trade_rows"] >= 30:
                score += 8
            else:
                score -= 5
            if 1 <= trading["open_positions"] <= 6:
                score += 4
            elif trading["open_positions"] > 8:
                score -= 5
            tops = ", ".join([f"{x['symbol']} ({x['count']})" for x in trading['top_symbols']]) or "none"
            return _autonomous_response(
                "trading_bot",
                "maximize equity returns by concentrating on proven symbol-level edge",
                score,
                [
                    f"Trades: {trading['trade_rows']} (BUY={trading['buy_count']}, SELL={trading['sell_count']})",
                    f"Estimated realized PnL: ${trading['realized_pnl_estimate']:,.2f}",
                    f"Open positions: {trading['open_positions']}",
                    f"Top symbols: {tops}",
                ],
                [
                    "Realized closes and positive PnL increase confidence in autonomous deployment.",
                    "Insufficient sample size lowers reliability of edge estimates.",
                    "Too many concurrent positions can dilute high-edge allocation.",
                ],
                [
                    "Throttle or pause symbols below median expectancy and reallocate to top performers.",
                    "Apply one stricter entry gate and monitor profit factor + drawdown in the next cycle.",
                    "Increase sizing only if both PnL per close and profit factor improve together.",
                ],
                "Reduce exposure immediately if max drawdown exceeds baseline or profit factor weakens for two cycles.",
            )
        if any(k in q for k in ("learn", "learning", "strategy", "signal", "improv", "return", "performance", "pnl")):
            tops = ", ".join([f"{x['symbol']} ({x['count']})" for x in trading['top_symbols']]) or "none yet"
            weaknesses = []
            if trading["sell_count"] == 0 and trading["buy_count"] > 0:
                weaknesses.append("limited closes reduces realized feedback for policy adaptation")
            if trading["trade_rows"] < 30:
                weaknesses.append("small sample size can hide weak symbols and overfit signals")
            return _build_returns_coach_response(
                "trading_bot",
                strategy["summary"],
                [
                    f"Trades logged: {trading['trade_rows']} (BUY={trading['buy_count']}, SELL={trading['sell_count']})",
                    f"Latest equity: ${trading['latest_equity']:,.2f}, cash ${trading['latest_cash']:,.2f}, open positions {trading['open_positions']}",
                    f"Estimated realized PnL (note-tagged closes): ${trading['realized_pnl_estimate']:,.2f}",
                    f"Most active symbols: {tops}",
                ],
                weaknesses,
                [
                    "Build a rolling 50-trade leaderboard by symbol and throttle position size on symbols below median expectancy.",
                    "Test a tighter confidence/edge gate for entries, then compare profit factor and drawdown over next 2 weeks.",
                    "Review adaptive policy drift weekly and reset/decay adjustments that underperform baseline signals.",
                ],
                [
                    "Profit factor (rolling 50 closes)",
                    "Realized PnL per closed trade",
                    "Symbol-level expectancy",
                    "Max drawdown vs baseline settings",
                ],
            )
        return (
            "Ask about trading bot learning, strategy rules, equity/PnL, or top traded symbols."
            + "\n\n"
            + "\n".join(_seven_day_experiment_plan("trading_bot", []))
        )

    asx = _summarize_asx_bot()
    forex = _summarize_forex_bot()
    if human_report_mode and not autonomous_mode:
        return _human_report_combined(status, trading, crypto, asx, forex)
    if autonomous_mode:
        running_count = sum(1 for b in ("trading_bot", "crypto_bot", "asx_bot", "forex_bot") if status[b]["running"])
        score = 10 + (running_count * 6)
        if trading["realized_pnl_estimate"] > 0:
            score += 6
        if asx["realized_pnl"] > 0:
            score += 6
        if crypto["has_error"] or forex["has_error"]:
            score -= 10
        return _autonomous_response(
            "combined",
            "maximize total portfolio returns by rotating capital toward bots with strongest current edge",
            score,
            [
                f"Running bots: {running_count}/4",
                f"Trading realized estimate: ${trading['realized_pnl_estimate']:,.2f}",
                f"ASX realized PnL: ${asx['realized_pnl']:,.2f}",
                f"Crypto errors: {'yes' if crypto['has_error'] else 'no'}, Forex errors: {'yes' if forex['has_error'] else 'no'}",
            ],
            [
                "Portfolio-level returns improve when capital follows current verified edge.",
                "Bots with runtime errors should not receive incremental allocation.",
                "Weekly rotation based on realized expectancy avoids stale allocation.",
            ],
            [
                "Rank bots daily by realized return per unit risk and shift allocation toward top 2 bots.",
                "Keep underperforming bot at minimum allocation until it clears threshold checks.",
                "Rebalance every 24h using the same scoring logic to enforce discipline.",
            ],
            "Cut allocation to any bot that fails 2 or more threshold checks at end of cycle.",
        )
    return (
        f"Bot status: trading={'running' if status['trading_bot']['running'] else 'stopped'}, "
        f"crypto={'running' if status['crypto_bot']['running'] else 'stopped'}, "
        f"asx={'running' if status['asx_bot']['running'] else 'stopped'}, "
        f"forex={'running' if status['forex_bot']['running'] else 'stopped'}.\n"
        f"Trading: {trading['trade_rows']} logged trades, equity ${trading['latest_equity']:,.2f}.\n"
        f"Crypto recent signal mentions: BUY={crypto['signal_mentions']['buy']}, SELL={crypto['signal_mentions']['sell']}, HOLD={crypto['signal_mentions']['hold']}.\n"
        f"ASX: {asx['trade_rows']} logged trades, equity ${asx['latest_equity']:,.2f}.\n"
        f"Forex recent signal mentions: BUY={forex['signal_mentions']['buy']}, SELL={forex['signal_mentions']['sell']}, HOLD={forex['signal_mentions']['hold']}.\n"
        "Ask specifically about trading_bot, crypto_bot, asx_bot, or forex_bot for deeper strategy/learning detail.\n\n"
        + "\n".join(_seven_day_experiment_plan("combined", []))
    )


def _bot_dashboard_payload():
    autonomy = _autonomy_dashboard_payload()
    auto_bots = autonomy.get("bots") or {}
    return {
        "status": _check_bot_status(),
        "trading_bot": {
            "metrics": {
                **_summarize_trading_bot(),
                "autonomy_improvement": (auto_bots.get("trading_bot") or {}).get("improvement") or {},
            },
            "strategy": _strategy_reference("trading_bot"),
        },
        "crypto_bot": {
            "metrics": {
                **_summarize_crypto_bot(),
                "autonomy_improvement": (auto_bots.get("crypto_bot") or {}).get("improvement") or {},
            },
            "strategy": _strategy_reference("crypto_bot"),
        },
        "asx_bot": {
            "metrics": {
                **_summarize_asx_bot(),
                "autonomy_improvement": (auto_bots.get("asx_bot") or {}).get("improvement") or {},
            },
            "strategy": _strategy_reference("asx_bot"),
        },
        "forex_bot": {
            "metrics": {
                **_summarize_forex_bot(),
                "autonomy_improvement": (auto_bots.get("forex_bot") or {}).get("improvement") or {},
            },
            "strategy": _strategy_reference("forex_bot"),
        },
        "tech_research_bot": {
            "metrics": _summarize_tech_research_bot(),
            "strategy": _strategy_reference("tech_research_bot"),
        },
        "autonomy": autonomy,
        "investment": _build_investment_progress(max_points=240),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _tmux_running(session):
    try:
        r = subprocess.run(["tmux", "has-session", "-t", session],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.returncode == 0
    except Exception:
        return False


def _last_log_lines(path, n=8):
    try:
        r = subprocess.run(["tail", f"-{n}", path],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.stdout.strip().splitlines()
    except Exception:
        return []


def _check_bot_status():
    trading_running = _tmux_running("trading_bot")
    crypto_running = _tmux_running("crypto_bot")
    asx_running = _tmux_running("asx_bot")
    forex_running = _tmux_running("forex_bot")
    tech_research_running = _tmux_running("tech_research_bot")
    return {
        "trading_bot": {
            "running": trading_running,
            "session": "trading_bot",
            "log": _last_log_lines(_BOT_CONFIG["trading_bot"]["log"]),
        },
        "crypto_bot": {
            "running": crypto_running,
            "session": "crypto_bot",
            "log": _last_log_lines(_BOT_CONFIG["crypto_bot"]["log"]),
        },
        "asx_bot": {
            "running": asx_running,
            "session": "asx_bot",
            "log": _last_log_lines(_BOT_CONFIG["asx_bot"]["log"]),
        },
        "forex_bot": {
            "running": forex_running,
            "session": "forex_bot",
            "log": _last_log_lines(_BOT_CONFIG["forex_bot"]["log"]),
        },
        "tech_research_bot": {
            "running": tech_research_running,
            "session": "tech_research_bot",
            "log": _last_log_lines(_BOT_CONFIG["tech_research_bot"]["log"]),
        },
        "all_running": trading_running and crypto_running and asx_running and forex_running,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _bot_control(bot_id, action):
    cfg = _BOT_CONFIG.get(bot_id)
    if not cfg:
        return False, f"Unknown bot: {bot_id}"
    session = cfg["session"]
    if action == "start":
        if _tmux_running(session):
            return True, f"{bot_id} is already running."
        try:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session,
                 f"cd {cfg['cwd']} && {cfg['cmd']}"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return True, f"{bot_id} started."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to start {bot_id}: {e.stderr.decode().strip()}"
    elif action == "stop":
        if not _tmux_running(session):
            return True, f"{bot_id} is not running."
        try:
            subprocess.run(["tmux", "kill-session", "-t", session],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True, f"{bot_id} stopped."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to stop {bot_id}: {e.stderr.decode().strip()}"
    elif action == "restart":
        try:
            if _tmux_running(session):
                subprocess.run(["tmux", "kill-session", "-t", session],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session,
                 f"cd {cfg['cwd']} && {cfg['cmd']}"],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            return True, f"{bot_id} restarted."
        except subprocess.CalledProcessError as e:
            return False, f"Failed to restart {bot_id}: {e.stderr.decode().strip()}"
    elif action == "reset_faults":
        try:
            state_path = _AUTONOMY_STATE_FILES.get(bot_id)
            if state_path and os.path.exists(state_path):
                os.remove(state_path)
                return True, f"{bot_id} fault state reset."
            return True, f"{bot_id} fault state already clear."
        except Exception as e:
            return False, f"Failed to reset faults for {bot_id}: {e}"
    return False, f"Unknown action: {action}"


def app(environ, start_response):
    """WSGI application for the Capitol Trades API workspace."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/bot_status":
        return json_response(start_response, _check_bot_status())

    if method == "GET" and path == "/bot_dashboard_data":
        return json_response(start_response, _bot_dashboard_payload())

    if method == "POST" and path == "/bot_copilot_chat":
        payload = _read_json_body(environ)
        bot_id = str(payload.get("bot") or "both")
        message = str(payload.get("message") or "").strip()
        if not message:
            return error_response(
                start_response,
                "message is required",
                status="400 Bad Request",
            )
        answer = _bot_copilot_answer(bot_id, message)
        return json_response(start_response, {
            "answer": answer,
            "bot": bot_id,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    if method == "POST" and path == "/bot_control":
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        bot_id = str((params.get("bot") or [""])[0]).strip()
        action = str((params.get("action") or [""])[0]).strip()
        ok, message = _bot_control(bot_id, action)
        status_code = "200 OK" if ok else "400 Bad Request"
        start_response(status_code, [("Content-Type", "application/json"),
                                     ("Access-Control-Allow-Origin", "*")])
        return [json.dumps({
            "ok": ok,
            "message": message,
            "bot": bot_id,
            "action": action,
            "timestamp": datetime.now(UTC).isoformat(),
        }).encode()]

    if method == "GET" and path == "/bot_status_page":
        try:
            with open("app/bot_status.html", "rb") as f:
                html = f.read()
            start_response("200 OK", [("Content-Type", "text/html")])
            return [html]
        except Exception as exc:
            return error_response(start_response, f"Could not load status page: {exc}",
                                  status="500 Internal Server Error")

    if method == "GET" and path == "/":
        return json_response(start_response, {
            "name": "Capitol Trades API",
            "status": "ok",
            "routes": ["/health", "/trades", "/politicians", "/sectors", "/news",
                       "/bot_status", "/bot_status_page", "/bot_control",
                       "/bot_dashboard_data", "/bot_copilot_chat"],
        })

    if method == "GET" and path == "/health":
        return json_response(start_response, {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
        })

    handler = ROUTES.get((method, path))
    if handler is None:
        return error_response(start_response, "Not Found", status="404 Not Found",
                              details={"path": path})
    try:
        return json_response(start_response, handler(environ))
    except ValueError as exc:
        return error_response(start_response, str(exc), status="400 Bad Request")
    except Exception as exc:
        return error_response(start_response, "Unable to fetch Capitol Trades data right now.",
                              status="502 Bad Gateway", details={"message": str(exc)})

