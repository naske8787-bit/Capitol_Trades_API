import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
CAPITOL_TRADES_API_URL = os.getenv("CAPITOL_TRADES_API_URL", "https://api.capitoltrades.com")
CAPITOL_TRADES_MAX_PAGES = int(os.getenv("CAPITOL_TRADES_MAX_PAGES", "5"))
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")  # Use paper trading for testing

# Trading settings
INITIAL_CAPITAL = 10000
RISK_PER_TRADE = 0.01  # 1%
MAX_POSITIONS = 5

# Model settings
MODEL_PATH = "models/trading_model.h5"