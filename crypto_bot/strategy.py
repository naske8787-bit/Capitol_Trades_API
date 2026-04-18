from config import (
    CRYPTO_MAX_POSITIONS,
    CRYPTO_MIN_NOTIONAL_PER_TRADE,
    CRYPTO_MIN_TREND_STRENGTH_PCT,
    CRYPTO_RISK_PER_TRADE,
    CRYPTO_RSI_BUY_THRESHOLD,
    CRYPTO_RSI_SELL_THRESHOLD,
    CRYPTO_STOP_LOSS_PCT,
    CRYPTO_TAKE_PROFIT_PCT,
)
from data_fetcher import fetch_crypto_data, preprocess_data


class TradingStrategy:
    def __init__(self):
        self.positions = {}
        self.last_analysis = {}

    def analyze_signal(self, symbol):
        symbol = symbol.upper()
        try:
            data = preprocess_data(fetch_crypto_data(symbol))
            if len(data) < 35:
                self.last_analysis[symbol] = {"reason": "not_enough_data"}
                return "HOLD"

            current_price = float(data["Close"].iloc[-1])
            ema_fast = float(data["ema_fast"].iloc[-1])
            ema_slow = float(data["ema_slow"].iloc[-1])
            rsi = float(data["rsi"].iloc[-1])
            momentum_pct = float(data["momentum_pct"].iloc[-1])
            trend_strength = (ema_fast - ema_slow) / max(abs(ema_slow), 1e-9)
            position = self.positions.get(symbol)

            self.last_analysis[symbol] = {
                "current_price": current_price,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "rsi": rsi,
                "momentum_pct": momentum_pct * 100,
                "trend_strength_pct": trend_strength * 100,
                "has_position": bool(position),
            }

            if position:
                entry_price = float(position["entry_price"])
                stop_loss_price = entry_price * (1 - CRYPTO_STOP_LOSS_PCT)
                take_profit_price = entry_price * (1 + CRYPTO_TAKE_PROFIT_PCT)
                self.last_analysis[symbol].update(
                    {
                        "entry_price": entry_price,
                        "stop_loss_price": stop_loss_price,
                        "take_profit_price": take_profit_price,
                    }
                )

                if current_price <= stop_loss_price:
                    return "SELL"
                if current_price >= take_profit_price and rsi >= CRYPTO_RSI_SELL_THRESHOLD:
                    return "SELL"
                if ema_fast < ema_slow and momentum_pct < 0:
                    return "SELL"
                return "HOLD"

            has_capacity = len(self.positions) < CRYPTO_MAX_POSITIONS
            bullish_trend = trend_strength >= CRYPTO_MIN_TREND_STRENGTH_PCT and ema_fast > ema_slow
            oversold_rebound = rsi <= CRYPTO_RSI_BUY_THRESHOLD and momentum_pct >= 0
            trend_continuation = bullish_trend and 45 <= rsi <= CRYPTO_RSI_SELL_THRESHOLD and momentum_pct > 0

            if has_capacity and (oversold_rebound or trend_continuation):
                return "BUY"
            return "HOLD"
        except Exception as e:
            print(f"Error analyzing signal for {symbol}: {e}")
            return "HOLD"

    def execute_trade(self, signal, symbol, broker):
        symbol = symbol.upper()
        try:
            if signal == "BUY":
                if symbol in self.positions:
                    return None

                capital = broker.get_account_balance()
                current_price = broker.get_current_price(symbol)
                notional = capital * CRYPTO_RISK_PER_TRADE
                if current_price <= 0 or notional < CRYPTO_MIN_NOTIONAL_PER_TRADE:
                    print(f"Skipping BUY for {symbol}: notional too small or price invalid.")
                    return None

                qty = round(notional / current_price, 6)
                if qty <= 0:
                    print(f"Skipping BUY for {symbol}: quantity rounded to zero.")
                    return None

                broker.buy(symbol, qty)
                self.positions[symbol] = {"entry_price": current_price, "qty": qty}
                print(f"BUY signal for {symbol}: {qty} units at ${current_price:.2f}")
                return {"action": "BUY", "symbol": symbol, "qty": qty, "price": current_price}

            if signal == "SELL":
                qty = broker.get_position_size(symbol) or float(self.positions.get(symbol, {}).get("qty", 0.0))
                if qty <= 0:
                    print(f"Skipping SELL for {symbol}: no open quantity found.")
                    self.positions.pop(symbol, None)
                    return None

                current_price = broker.get_current_price(symbol)
                broker.sell(symbol, qty)
                self.positions.pop(symbol, None)
                print(f"SELL signal for {symbol}: {qty} units at ${current_price:.2f}")
                return {"action": "SELL", "symbol": symbol, "qty": qty, "price": current_price}
        except Exception as e:
            print(f"Error executing trade for {symbol}: {e}")
        return None
