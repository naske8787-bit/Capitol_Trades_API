import os
import re
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)


def _validate_env_file(env_path):
    if not os.path.exists(env_path):
        return

    key_prefix_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")
    embedded_key_re = re.compile(r"[A-Z][A-Z0-9_]{2,}\s*=")

    with open(env_path, "r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if not key_prefix_re.match(line):
                continue

            _, value = line.split("=", 1)
            for match in embedded_key_re.finditer(value):
                idx = match.start()
                prev = value[idx - 1] if idx > 0 else ""
                if prev.isalnum() or prev == "_":
                    token = match.group(0).strip()
                    raise RuntimeError(
                        f"Malformed .env at {env_path}:{line_no} - detected concatenated assignment before '{token}'. "
                        "Put each KEY=VALUE on its own line."
                    )

for env_path in (
    os.path.join(BASE_DIR, ".env"),
    os.path.join(REPO_ROOT, ".env"),
):
    if os.path.exists(env_path):
        _validate_env_file(env_path)
        load_dotenv(env_path, override=True)


def _parse_symbol_list(value, default):
    raw_value = value or default
    symbols = []
    for part in raw_value.split(","):
        symbol = part.strip().upper()
        if not symbol:
            continue
        if "/" not in symbol and symbol.endswith("USD") and len(symbol) > 3:
            symbol = f"{symbol[:-3]}/USD"
        symbols.append(symbol)
    return symbols


def _parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

CRYPTO_WATCHLIST = _parse_symbol_list(
    os.getenv("CRYPTO_WATCHLIST"),
    "BTC/USD,ETH/USD,SOL/USD",
)
CRYPTO_DATA_INTERVAL = os.getenv("CRYPTO_DATA_INTERVAL", "1h")
CRYPTO_LOOKBACK_PERIOD = os.getenv("CRYPTO_LOOKBACK_PERIOD", "90d")
CRYPTO_FAST_EMA_WINDOW = int(os.getenv("CRYPTO_FAST_EMA_WINDOW", "10"))
CRYPTO_SLOW_EMA_WINDOW = int(os.getenv("CRYPTO_SLOW_EMA_WINDOW", "30"))
CRYPTO_RSI_PERIOD = int(os.getenv("CRYPTO_RSI_PERIOD", "14"))
CRYPTO_RSI_BUY_THRESHOLD = float(os.getenv("CRYPTO_RSI_BUY_THRESHOLD", "40"))
CRYPTO_RSI_SELL_THRESHOLD = float(os.getenv("CRYPTO_RSI_SELL_THRESHOLD", "68"))
CRYPTO_RISK_PER_TRADE = float(os.getenv("CRYPTO_RISK_PER_TRADE", "0.10"))
CRYPTO_MAX_POSITIONS = int(os.getenv("CRYPTO_MAX_POSITIONS", "3"))
CRYPTO_STOP_LOSS_PCT = float(os.getenv("CRYPTO_STOP_LOSS_PCT", "0.03"))
CRYPTO_TAKE_PROFIT_PCT = float(os.getenv("CRYPTO_TAKE_PROFIT_PCT", "0.07"))
CRYPTO_LOOP_INTERVAL_SECONDS = int(os.getenv("CRYPTO_LOOP_INTERVAL_SECONDS", "300"))
CRYPTO_MIN_NOTIONAL_PER_TRADE = float(os.getenv("CRYPTO_MIN_NOTIONAL_PER_TRADE", "25"))
CRYPTO_MIN_TREND_STRENGTH_PCT = float(os.getenv("CRYPTO_MIN_TREND_STRENGTH_PCT", "0.002"))
CRYPTO_SELL_QTY_BUFFER_PCT = float(os.getenv("CRYPTO_SELL_QTY_BUFFER_PCT", "0.998"))
CRYPTO_PAPER_ONLY = _parse_bool(os.getenv("CRYPTO_PAPER_ONLY"), True)

# MACD parameters
CRYPTO_MACD_FAST = int(os.getenv("CRYPTO_MACD_FAST", "12"))
CRYPTO_MACD_SLOW = int(os.getenv("CRYPTO_MACD_SLOW", "26"))
CRYPTO_MACD_SIGNAL = int(os.getenv("CRYPTO_MACD_SIGNAL", "9"))

# ATR-based trailing stop
CRYPTO_ATR_PERIOD = int(os.getenv("CRYPTO_ATR_PERIOD", "14"))
CRYPTO_ATR_STOP_MULTIPLIER = float(os.getenv("CRYPTO_ATR_STOP_MULTIPLIER", "2.0"))

# Volume filter: require volume >= this percentile of recent history (0 = disabled)
CRYPTO_MIN_VOLUME_PERCENTILE = float(os.getenv("CRYPTO_MIN_VOLUME_PERCENTILE", "40"))

# External research gating thresholds for entries.
# More negative values are more permissive (allow entries under bearish headlines).
CRYPTO_RESEARCH_HARD_BLOCK_SCORE = float(os.getenv("CRYPTO_RESEARCH_HARD_BLOCK_SCORE", "-12"))
CRYPTO_RESEARCH_SOFT_BLOCK_SCORE = float(os.getenv("CRYPTO_RESEARCH_SOFT_BLOCK_SCORE", "-8"))
CRYPTO_RESEARCH_ENTRY_GUARD_SCORE = float(os.getenv("CRYPTO_RESEARCH_ENTRY_GUARD_SCORE", "-6"))

# Autonomous execution controls
AUTONOMOUS_EXECUTION_ENABLED = _parse_bool(os.getenv("AUTONOMOUS_EXECUTION_ENABLED"), True)
AUTONOMOUS_MIN_CLOSED_TRADES = int(os.getenv("AUTONOMOUS_MIN_CLOSED_TRADES", "6"))
AUTONOMOUS_MIN_WIN_RATE = float(os.getenv("AUTONOMOUS_MIN_WIN_RATE", "0.5"))
AUTONOMOUS_MIN_PROFIT_FACTOR = float(os.getenv("AUTONOMOUS_MIN_PROFIT_FACTOR", "1.05"))
AUTONOMOUS_MIN_REALIZED_PNL_7D = float(os.getenv("AUTONOMOUS_MIN_REALIZED_PNL_7D", "0"))
AUTONOMOUS_MAX_DRAWDOWN_7D_PCT = float(os.getenv("AUTONOMOUS_MAX_DRAWDOWN_7D_PCT", "0.08"))
AUTONOMY_LEARNING_ENABLED = _parse_bool(os.getenv("AUTONOMY_LEARNING_ENABLED"), True)
AUTONOMY_AGGRESSIVE_MIN_CONFIDENCE = float(os.getenv("AUTONOMY_AGGRESSIVE_MIN_CONFIDENCE", "0.75"))
AUTONOMY_AGGRESSIVE_MIN_CLOSED_TRADES = int(
    os.getenv("AUTONOMY_AGGRESSIVE_MIN_CLOSED_TRADES", str(AUTONOMOUS_MIN_CLOSED_TRADES))
)
AUTONOMY_AGGRESSIVE_COOLDOWN_HOURS = int(os.getenv("AUTONOMY_AGGRESSIVE_COOLDOWN_HOURS", "24"))
AUTONOMY_LOSS_EVENT_MIN_PNL = float(os.getenv("AUTONOMY_LOSS_EVENT_MIN_PNL", "-25"))
AUTONOMY_RECOVERY_EVENT_MIN_PNL = float(os.getenv("AUTONOMY_RECOVERY_EVENT_MIN_PNL", "25"))

# External internet research sentiment controls
EXTERNAL_RESEARCH_ENABLED = _parse_bool(os.getenv("EXTERNAL_RESEARCH_ENABLED"), True)
EXTERNAL_RESEARCH_CACHE_TTL_SECONDS = int(os.getenv("EXTERNAL_RESEARCH_CACHE_TTL_SECONDS", "1800"))
SEARCH_PROVIDER = str(os.getenv("SEARCH_PROVIDER", "serpapi")).strip().lower()  # brave | serpapi
SEARCH_API_KEY = str(os.getenv("SEARCH_API_KEY") or os.getenv("SERPAPI_API_KEY") or "").strip()
SEARCH_ENGINE = str(os.getenv("SEARCH_ENGINE", "google")).strip().lower()  # for serpapi
EXTERNAL_RESEARCH_MIN_HEADLINES = int(os.getenv("EXTERNAL_RESEARCH_MIN_HEADLINES", "12"))
EXTERNAL_RESEARCH_MIN_SOURCES = int(os.getenv("EXTERNAL_RESEARCH_MIN_SOURCES", "3"))
EXTERNAL_RESEARCH_MIN_FRESH_RATIO = float(os.getenv("EXTERNAL_RESEARCH_MIN_FRESH_RATIO", "0.25"))

# Automatic strategy improvement controls
AUTO_IMPLEMENT_IMPROVEMENTS_ENABLED = _parse_bool(os.getenv("AUTO_IMPLEMENT_IMPROVEMENTS_ENABLED"), True)
AUTO_IMPROVEMENT_REBALANCE_HOURS = int(os.getenv("AUTO_IMPROVEMENT_REBALANCE_HOURS", "24"))
AUTO_IMPROVEMENT_LOOKBACK_DAYS = int(os.getenv("AUTO_IMPROVEMENT_LOOKBACK_DAYS", "14"))
AUTO_IMPROVEMENT_MIN_TRADES_PER_SYMBOL = int(os.getenv("AUTO_IMPROVEMENT_MIN_TRADES_PER_SYMBOL", "3"))

# Market Regime Configuration
MARKET_REGIME_SYMBOL = os.getenv("MARKET_REGIME_SYMBOL", "BTC/USD")
MARKET_REGIME_SHORT_WINDOW = int(os.getenv("MARKET_REGIME_SHORT_WINDOW", "20"))
MARKET_REGIME_LONG_WINDOW = int(os.getenv("MARKET_REGIME_LONG_WINDOW", "50"))

# Crypto Influencer Monitor
# Tracks public statements from known market-moving influencers via Brave Search
# and generates manipulation signals that feed into entry/exit decisions.
INFLUENCER_MONITOR_ENABLED = _parse_bool(os.getenv("INFLUENCER_MONITOR_ENABLED"), True)
# How often to refresh influencer search results (seconds).  Default 15 min.
INFLUENCER_MONITOR_CACHE_TTL_SECONDS = int(os.getenv("INFLUENCER_MONITOR_CACHE_TTL_SECONDS", "900"))
# net_signal threshold above which the bot treats this as a pump and boosts entries.
INFLUENCER_PUMP_TRADE_SCORE = float(os.getenv("INFLUENCER_PUMP_TRADE_SCORE", "3.0"))
# net_signal threshold below which the bot treats this as a dump and forces exits.
INFLUENCER_DUMP_SELL_SCORE = float(os.getenv("INFLUENCER_DUMP_SELL_SCORE", "-3.0"))
# manipulation_score above this causes the bot to switch to a tighter take-profit
# "pump-ride" mode (exit sooner before the inevitable dump).
INFLUENCER_MANIPULATION_RIDE_SCORE = float(os.getenv("INFLUENCER_MANIPULATION_RIDE_SCORE", "5.0"))
# manipulation_score below this forces an immediate sell of any open position.
INFLUENCER_MANIPULATION_DUMP_SCORE = float(os.getenv("INFLUENCER_MANIPULATION_DUMP_SCORE", "-5.0"))
# When coordination is detected (2+ influencers same direction) and this flag
# is True, apply an extra confirmation check before buying into the pump.
INFLUENCER_REQUIRE_TECHNICAL_CONFIRM = _parse_bool(
    os.getenv("INFLUENCER_REQUIRE_TECHNICAL_CONFIRM"), True
)
