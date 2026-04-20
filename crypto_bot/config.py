import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)

for env_path in (
    os.path.join(BASE_DIR, ".env"),
    os.path.join(REPO_ROOT, "trading_bot", ".env"),
    os.path.join(REPO_ROOT, ".env"),
):
    if os.path.exists(env_path):
        load_dotenv(env_path)


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
