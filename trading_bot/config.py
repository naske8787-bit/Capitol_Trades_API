import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _parse_symbol_list(value, default):
    raw_value = value or default
    return [symbol.strip().upper() for symbol in raw_value.split(",") if symbol.strip()]


# API Keys
CAPITOL_TRADES_API_URL = os.getenv("CAPITOL_TRADES_API_URL", "https://api.capitoltrades.com")
CAPITOL_TRADES_MAX_PAGES = int(os.getenv("CAPITOL_TRADES_MAX_PAGES", "5"))
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")  # Use paper trading for testing

# Trading settings
INITIAL_CAPITAL = 10000
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.0075"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))
BUY_THRESHOLD_PCT = float(os.getenv("BUY_THRESHOLD_PCT", "0.005"))
SELL_THRESHOLD_PCT = float(os.getenv("SELL_THRESHOLD_PCT", "0.004"))
MIN_SENTIMENT_TO_BUY = int(os.getenv("MIN_SENTIMENT_TO_BUY", "2"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.03"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.06"))
MIN_TREND_STRENGTH_PCT = float(os.getenv("MIN_TREND_STRENGTH_PCT", "0.003"))
TRADE_COOLDOWN_MINUTES = int(os.getenv("TRADE_COOLDOWN_MINUTES", "240"))
MARKET_REGIME_SYMBOL = os.getenv("MARKET_REGIME_SYMBOL", "SPY")
MARKET_REGIME_SHORT_WINDOW = int(os.getenv("MARKET_REGIME_SHORT_WINDOW", "50"))
MARKET_REGIME_LONG_WINDOW = int(os.getenv("MARKET_REGIME_LONG_WINDOW", "200"))
STOCK_DATA_CACHE_TTL_SECONDS = int(os.getenv("STOCK_DATA_CACHE_TTL_SECONDS", "900"))
WATCHLIST = _parse_symbol_list(
    os.getenv("WATCHLIST"),
    "AAPL,MSFT,NVDA,GOOGL,TSLA,AMZN",
)
TRAINING_SYMBOLS = _parse_symbol_list(
    os.getenv("TRAINING_SYMBOLS"),
    ",".join(WATCHLIST),
)

# Model settings
MODEL_PATH = os.path.join(BASE_DIR, "models", "trading_model.h5")