import pandas as pd
import yfinance as yf

from config import (
    CRYPTO_DATA_INTERVAL,
    CRYPTO_FAST_EMA_WINDOW,
    CRYPTO_LOOKBACK_PERIOD,
    CRYPTO_RSI_PERIOD,
    CRYPTO_SLOW_EMA_WINDOW,
)


def to_yfinance_symbol(symbol):
    return symbol.replace("/", "-").upper()


def to_alpaca_symbol(symbol):
    return symbol.upper()


def fetch_crypto_data(symbol, period=None, interval=None):
    ticker = to_yfinance_symbol(symbol)
    data = yf.download(
        ticker,
        period=period or CRYPTO_LOOKBACK_PERIOD,
        interval=interval or CRYPTO_DATA_INTERVAL,
        progress=False,
        auto_adjust=False,
    )
    if isinstance(data, pd.Series):
        data = data.to_frame()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def preprocess_data(data):
    data = data.copy().dropna()
    close = pd.to_numeric(data["Close"], errors="coerce")
    data["ema_fast"] = close.ewm(span=CRYPTO_FAST_EMA_WINDOW, adjust=False).mean()
    data["ema_slow"] = close.ewm(span=CRYPTO_SLOW_EMA_WINDOW, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / max(CRYPTO_RSI_PERIOD, 1), min_periods=CRYPTO_RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / max(CRYPTO_RSI_PERIOD, 1), min_periods=CRYPTO_RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    data["rsi"] = (100 - (100 / (1 + rs))).fillna(50.0)
    data["momentum_pct"] = close.pct_change(3).fillna(0.0)
    return data.dropna()
