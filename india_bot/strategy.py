"""Trading strategy for the India bot.

Uses a combination of:
  - EMA crossover (9/21 EMA) for trend direction
  - RSI (14) for momentum confirmation
  - MACD for additional confirmation
  - Market regime filter using NIFTY 50

No pre-trained ML model is required — pure technical analysis.
"""

import time

import pandas as pd

from config import (
    BUY_THRESHOLD_PCT,
    MARKET_REGIME_LONG_WINDOW,
    MARKET_REGIME_SHORT_WINDOW,
    MARKET_REGIME_SYMBOL,
    MAX_POSITIONS,
    RISK_PER_TRADE,
    SELL_THRESHOLD_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TRADE_COOLDOWN_MINUTES,
)
from data_fetcher import fetch_realtime_price, fetch_stock_data, preprocess_data

# RSI / EMA config
RSI_PERIOD = 14
EMA_SHORT = 9
EMA_LONG = 21
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = RSI_PERIOD) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _macd(series: pd.Series):
    fast = _ema(series, MACD_FAST)
    slow = _ema(series, MACD_SLOW)
    macd_line = fast - slow
    signal_line = _ema(macd_line, MACD_SIGNAL)
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])


class TradingStrategy:
    def __init__(self):
        self.positions: dict = {}
        self.last_analysis: dict = {}
        self.last_trade_times: dict = {}
        self._market_state_cache = None
        self._market_state_ts = 0.0

    def _in_cooldown(self, symbol: str) -> tuple[bool, float]:
        cooldown_secs = max(0, TRADE_COOLDOWN_MINUTES) * 60
        last_ts = self.last_trade_times.get(symbol.upper(), 0.0)
        remaining = max(0.0, cooldown_secs - (time.time() - last_ts))
        return remaining > 0, remaining

    def _sync_position(self, symbol: str, broker=None):
        symbol = symbol.upper()
        if broker:
            pos = broker.get_position(symbol)
            if pos:
                prev = self.positions.get(symbol, {})
                pos["entry_price"] = float(pos.get("entry_price") or prev.get("entry_price") or 0.0)
                self.positions[symbol] = pos
                return pos
            self.positions.pop(symbol, None)
        return self.positions.get(symbol)

    def _get_market_regime(self) -> dict:
        now = time.time()
        if self._market_state_cache and now - self._market_state_ts < 300:
            return self._market_state_cache

        try:
            data = preprocess_data(fetch_stock_data(MARKET_REGIME_SYMBOL, period="1y"))
            close = data["Close"].astype(float)
            short_ma = float(close.tail(min(MARKET_REGIME_SHORT_WINDOW, len(close))).mean())
            long_ma = float(close.tail(min(MARKET_REGIME_LONG_WINDOW, len(close))).mean())
            current_price = float(close.iloc[-1])
            favorable = current_price >= short_ma and short_ma >= long_ma * 0.995
            self._market_state_cache = {
                "current_price": current_price,
                "short_ma": short_ma,
                "long_ma": long_ma,
                "favorable": favorable,
            }
        except Exception as e:
            self._market_state_cache = {"favorable": True, "error": str(e)}

        self._market_state_ts = now
        return self._market_state_cache

    def analyze_signal(self, symbol: str, broker=None) -> str:
        symbol = symbol.upper()
        try:
            data = preprocess_data(fetch_stock_data(symbol, period="1y"))
            if len(data) < MACD_SLOW + MACD_SIGNAL + 5:
                self.last_analysis[symbol] = {"reason": "not_enough_data"}
                return "HOLD"

            close = data["Close"].astype(float)
            current_price = float(close.iloc[-1])

            # Indicators
            ema_short_val = float(_ema(close, EMA_SHORT).iloc[-1])
            ema_long_val = float(_ema(close, EMA_LONG).iloc[-1])
            rsi_val = _rsi(close)
            macd_line, macd_sig, macd_hist = _macd(close)
            recent_return = float(close.pct_change(5).fillna(0.0).iloc[-1])

            ema_bullish = ema_short_val > ema_long_val
            rsi_oversold = rsi_val < 35
            rsi_overbought = rsi_val > 70
            macd_bullish = macd_hist > 0

            market = self._get_market_regime()
            in_cooldown, cooldown_remaining = self._in_cooldown(symbol)
            position = self._sync_position(symbol, broker)

            self.last_analysis[symbol] = {
                "current_price": current_price,
                "ema_short": ema_short_val,
                "ema_long": ema_long_val,
                "rsi": rsi_val,
                "macd_line": macd_line,
                "macd_signal": macd_sig,
                "macd_histogram": macd_hist,
                "recent_return_pct": recent_return * 100,
                "market_favorable": bool(market.get("favorable", True)),
                "has_position": bool(position),
                "cooldown_remaining_minutes": cooldown_remaining / 60,
            }

            # --- Exit logic ---
            if position:
                entry_price = float(position.get("entry_price") or current_price)
                if entry_price <= 0:
                    entry_price = current_price
                stop_loss_price = entry_price * (1 - STOP_LOSS_PCT)
                take_profit_price = entry_price * (1 + TAKE_PROFIT_PCT)
                self.last_analysis[symbol].update(
                    {"entry_price": entry_price, "stop_loss_price": stop_loss_price, "take_profit_price": take_profit_price}
                )

                if current_price <= stop_loss_price:
                    return "SELL"
                if current_price >= take_profit_price:
                    if rsi_overbought or not macd_bullish:
                        return "SELL"
                if not ema_bullish and rsi_overbought:
                    return "SELL"
                if recent_return <= -SELL_THRESHOLD_PCT and not macd_bullish:
                    return "SELL"
                return "HOLD"

            # --- Entry logic ---
            if in_cooldown:
                return "HOLD"

            open_count = broker.get_open_positions_count() if broker else len(self.positions)
            if open_count >= MAX_POSITIONS:
                return "HOLD"

            if not market.get("favorable", True):
                return "HOLD"

            # Buy when EMA crossover up + MACD bullish + RSI not overbought
            if ema_bullish and macd_bullish and not rsi_overbought:
                if rsi_oversold or recent_return >= BUY_THRESHOLD_PCT:
                    return "BUY"

            return "HOLD"

        except Exception as e:
            print(f"[Strategy] Error analyzing {symbol}: {e}")
            self.last_analysis[symbol] = {"error": str(e)}
            return "HOLD"

    def execute_trade(self, signal: str, symbol: str, broker) -> dict | None:
        symbol = symbol.upper()
        if signal == "BUY":
            qty = broker.calculate_qty(symbol)
            broker.buy(symbol, qty)
            price = broker.get_current_price(symbol)
            self.last_trade_times[symbol] = time.time()
            return {"action": "BUY", "symbol": symbol, "qty": qty, "price": price}

        if signal == "SELL":
            qty = int(broker.get_position_size(symbol))
            if qty <= 0:
                return None
            broker.sell(symbol, qty)
            price = broker.get_current_price(symbol)
            self.last_trade_times[symbol] = time.time()
            return {"action": "SELL", "symbol": symbol, "qty": qty, "price": price}

        return None
