import time

from config import (
    BUY_THRESHOLD_PCT,
    MARKET_REGIME_LONG_WINDOW,
    MARKET_REGIME_SHORT_WINDOW,
    MARKET_REGIME_SYMBOL,
    MAX_POSITIONS,
    MIN_SENTIMENT_TO_BUY,
    MIN_TREND_STRENGTH_PCT,
    RISK_PER_TRADE,
    SELL_THRESHOLD_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TRADE_COOLDOWN_MINUTES,
)
from data_fetcher import fetch_capitol_trades, fetch_stock_data, preprocess_data
from model import load_trained_model, predict_price


class TradingStrategy:
    def __init__(self):
        self.positions = {}
        self.model_cache = {}
        self.last_analysis = {}
        self.last_trade_times = {}
        self.market_state_cache = None
        self.market_state_ts = 0.0

    def _get_model_bundle(self, symbol):
        symbol = symbol.upper()
        if symbol not in self.model_cache:
            self.model_cache[symbol] = load_trained_model(symbol=symbol)
        return self.model_cache[symbol]

    @staticmethod
    def _calculate_sentiment(trades, symbol):
        symbol = symbol.upper()
        buy_signals = 0
        sell_signals = 0

        for trade in trades:
            if str(trade.get("symbol") or "").upper() != symbol:
                continue
            action = str(trade.get("action") or trade.get("trade_type") or "").lower()
            if "buy" in action or "purchase" in action:
                buy_signals += 1
            elif "sell" in action or "sale" in action:
                sell_signals += 1

        return buy_signals - sell_signals, buy_signals, sell_signals

    def _sync_position(self, symbol, broker=None):
        symbol = symbol.upper()
        if broker and hasattr(broker, "get_position"):
            broker_position = broker.get_position(symbol)
            if broker_position:
                previous = self.positions.get(symbol, {})
                entry_price = float(broker_position.get("entry_price") or previous.get("entry_price") or 0.0)
                broker_position["entry_price"] = entry_price
                self.positions[symbol] = broker_position
                return broker_position
            self.positions.pop(symbol, None)
        return self.positions.get(symbol)

    def _get_market_regime(self):
        now = time.time()
        if self.market_state_cache and now - self.market_state_ts < 300:
            return self.market_state_cache

        try:
            market_data = preprocess_data(fetch_stock_data(MARKET_REGIME_SYMBOL, period="1y"))
            close = market_data["Close"].astype(float)
            short_window = min(MARKET_REGIME_SHORT_WINDOW, len(close))
            long_window = min(MARKET_REGIME_LONG_WINDOW, len(close))
            short_ma = float(close.tail(short_window).mean())
            long_ma = float(close.tail(long_window).mean())
            current_price = float(close.iloc[-1])
            favorable = current_price >= short_ma and short_ma >= long_ma * 0.995
            self.market_state_cache = {
                "symbol": MARKET_REGIME_SYMBOL,
                "current_price": current_price,
                "short_ma": short_ma,
                "long_ma": long_ma,
                "favorable": favorable,
            }
        except Exception as e:
            self.market_state_cache = {
                "symbol": MARKET_REGIME_SYMBOL,
                "favorable": True,
                "error": str(e),
            }

        self.market_state_ts = now
        return self.market_state_cache

    def _in_cooldown(self, symbol):
        cooldown_seconds = max(0, TRADE_COOLDOWN_MINUTES) * 60
        last_trade_ts = self.last_trade_times.get(symbol.upper(), 0.0)
        remaining_seconds = max(0.0, cooldown_seconds - (time.time() - last_trade_ts))
        return remaining_seconds > 0, remaining_seconds

    def analyze_signal(self, symbol, broker=None):
        """Analyze buy/sell signals using ML prediction, sentiment, trend, and regime filters."""
        symbol = symbol.upper()
        try:
            data = preprocess_data(fetch_stock_data(symbol, period="1y"))
            if len(data) < 60:
                self.last_analysis[symbol] = {"reason": "not_enough_data"}
                return "HOLD"

            model, scaler = self._get_model_bundle(symbol)
            close = data["Close"].astype(float)
            recent_prices = close.tail(60).to_numpy()
            predicted_price = predict_price(model, scaler, recent_prices)

            current_price = float(close.iloc[-1])
            predicted_change = (predicted_price - current_price) / current_price
            short_trend = float(close.tail(min(20, len(close))).mean())
            long_trend = float(close.tail(min(50, len(close))).mean())
            recent_return = float(close.pct_change(5).fillna(0.0).iloc[-1])
            trend_strength = (short_trend - long_trend) / max(abs(long_trend), 1e-9)

            trades = fetch_capitol_trades()
            sentiment, buy_signals, sell_signals = self._calculate_sentiment(trades, symbol)
            position = self._sync_position(symbol, broker)
            market_state = self._get_market_regime()
            in_cooldown, cooldown_remaining = self._in_cooldown(symbol)

            self.last_analysis[symbol] = {
                "predicted_price": predicted_price,
                "current_price": current_price,
                "predicted_change_pct": predicted_change * 100,
                "sentiment": sentiment,
                "buy_signals": buy_signals,
                "sell_signals": sell_signals,
                "short_trend": short_trend,
                "long_trend": long_trend,
                "trend_strength_pct": trend_strength * 100,
                "recent_return_pct": recent_return * 100,
                "market_favorable": bool(market_state.get("favorable", True)),
                "cooldown_remaining_minutes": cooldown_remaining / 60,
                "has_position": bool(position),
            }

            if position:
                entry_price = float(position.get("entry_price") or current_price)
                if entry_price <= 0:
                    entry_price = current_price
                stop_loss_price = entry_price * (1 - STOP_LOSS_PCT)
                take_profit_price = entry_price * (1 + TAKE_PROFIT_PCT)
                self.last_analysis[symbol].update(
                    {
                        "entry_price": entry_price,
                        "stop_loss_price": stop_loss_price,
                        "take_profit_price": take_profit_price,
                    }
                )

                if current_price <= stop_loss_price:
                    return "SELL"
                if current_price >= take_profit_price and (
                    predicted_change <= BUY_THRESHOLD_PCT or sentiment <= 0 or trend_strength < 0
                ):
                    return "SELL"
                if predicted_change <= -SELL_THRESHOLD_PCT and (
                    sentiment < 0 or trend_strength < 0 or recent_return < 0
                ):
                    return "SELL"
                if sentiment <= -2 and recent_return < 0:
                    return "SELL"
                if short_trend < long_trend and recent_return <= -SELL_THRESHOLD_PCT:
                    return "SELL"
                return "HOLD"

            try:
                open_positions_count = broker.get_open_positions_count() if broker else len(self.positions)
            except Exception:
                open_positions_count = len(self.positions)

            has_capacity = open_positions_count < MAX_POSITIONS
            has_model_edge = predicted_change >= BUY_THRESHOLD_PCT
            has_strong_model_edge = predicted_change >= BUY_THRESHOLD_PCT * 1.5
            has_positive_sentiment = sentiment >= MIN_SENTIMENT_TO_BUY
            has_strong_sentiment = sentiment >= MIN_SENTIMENT_TO_BUY + 2
            trend_confirmation = (
                trend_strength >= MIN_TREND_STRENGTH_PCT and current_price > short_trend > long_trend
            )
            positive_momentum = recent_return >= BUY_THRESHOLD_PCT

            if not has_capacity or in_cooldown:
                return "HOLD"
            if not market_state.get("favorable", True) and not has_strong_sentiment:
                return "HOLD"

            if trend_confirmation:
                if has_model_edge and has_positive_sentiment:
                    return "BUY"
                if has_strong_model_edge and positive_momentum:
                    return "BUY"
                if has_strong_sentiment and positive_momentum:
                    return "BUY"

            return "HOLD"
        except Exception as e:
            print(f"Error analyzing signal for {symbol}: {e}")
            return "HOLD"

    def execute_trade(self, signal, symbol, broker):
        """Execute trades with tighter position sizing and restart-safe risk controls."""
        symbol = symbol.upper()
        try:
            if signal == "BUY":
                if symbol in self.positions:
                    return None
                if broker.get_open_positions_count() >= MAX_POSITIONS:
                    print(f"Skipping BUY for {symbol}: already at max positions.")
                    return None

                capital = broker.get_account_balance()
                current_price = broker.get_current_price(symbol)
                if current_price <= 0 or capital <= 0:
                    print(f"Skipping BUY for {symbol}: invalid capital or price.")
                    return None

                target_qty = int((capital * RISK_PER_TRADE) / current_price)
                max_affordable_qty = int(capital // current_price)
                qty = min(max_affordable_qty, max(1, target_qty)) if max_affordable_qty > 0 else 0
                if qty <= 0:
                    print(f"Skipping BUY for {symbol}: insufficient buying power for one share.")
                    return None

                broker.buy(symbol, qty)
                self.positions[symbol] = {"entry_price": current_price, "qty": qty}
                self.last_trade_times[symbol] = time.time()
                print(f"BUY signal for {symbol}: {qty} shares at ${current_price:.2f}")
                return {"action": "BUY", "symbol": symbol, "qty": qty, "price": current_price}

            if signal == "SELL":
                synced_position = self._sync_position(symbol, broker)
                qty = int(round(broker.get_position_size(symbol)))
                if qty <= 0:
                    qty = int((synced_position or self.positions.get(symbol, {})).get("qty", 0))
                if qty <= 0:
                    print(f"Skipping SELL for {symbol}: no open quantity found.")
                    self.positions.pop(symbol, None)
                    return None

                current_price = broker.get_current_price(symbol)
                broker.sell(symbol, qty)
                self.positions.pop(symbol, None)
                self.last_trade_times[symbol] = time.time()
                print(f"SELL signal for {symbol}: {qty} shares at ${current_price:.2f}")
                return {"action": "SELL", "symbol": symbol, "qty": qty, "price": current_price}
        except Exception as e:
            print(f"Error executing trade for {symbol}: {e}")
        return None