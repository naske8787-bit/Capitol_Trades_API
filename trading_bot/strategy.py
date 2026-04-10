from model import load_trained_model, predict_price
from data_fetcher import fetch_stock_data, fetch_capitol_trades, preprocess_data
from config import RISK_PER_TRADE, MAX_POSITIONS

class TradingStrategy:
    def __init__(self):
        self.model, self.scaler = load_trained_model()
        self.positions = []

    def analyze_signal(self, symbol):
        """Analyze buy/sell signal based on ML prediction and Capitol Trades."""
        try:
            data = fetch_stock_data(symbol, period="2y")
            data = preprocess_data(data)

            # Get recent data for prediction
            recent_prices = data['Close'].tail(60).values
            predicted_price = predict_price(self.model, self.scaler, recent_prices)

            current_price = float(data['Close'].iloc[-1].item() if hasattr(data['Close'].iloc[-1], 'item') else data['Close'].iloc[-1])

            # Fetch Capitol Trades for sentiment
            trades = fetch_capitol_trades()
            # Simple sentiment: count buys vs sells for the symbol (assuming symbol in trades)
            buy_signals = sum(1 for trade in trades if trade.get('action') == 'buy' and trade.get('symbol') == symbol)
            sell_signals = sum(1 for trade in trades if trade.get('action') == 'sell' and trade.get('symbol') == symbol)

            sentiment = buy_signals - sell_signals

            # Decision logic - simplified for testing
            if predicted_price > current_price * 1.005 and len(self.positions) < MAX_POSITIONS:  # Lower threshold for BUY
                return 'BUY'
            elif predicted_price < current_price * 0.995 and symbol in self.positions:  # Only SELL if we have position
                return 'SELL'
            else:
                return 'HOLD'
        except Exception as e:
            print(f"Error analyzing signal for {symbol}: {e}")
            return 'HOLD'

    def execute_trade(self, signal, symbol, broker):
        """Execute trade via broker."""
        try:
            if signal == 'BUY':
                # Calculate position size
                capital = broker.get_account_balance()
                current_price = broker.get_current_price(symbol)
                if current_price > 0:
                    position_size = capital * RISK_PER_TRADE / current_price
                    broker.buy(symbol, position_size)
                    self.positions.append(symbol)
                    print(f"BUY signal for {symbol}: {position_size:.2f} shares at ${current_price:.2f}")
            elif signal == 'SELL' and symbol in self.positions:
                broker.sell(symbol, broker.get_position_size(symbol))
                self.positions.remove(symbol)
                print(f"SELL signal for {symbol}")
        except Exception as e:
            print(f"Error executing trade for {symbol}: {e}")