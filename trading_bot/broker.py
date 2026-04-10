from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from config import ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL

class Broker:
    def __init__(self):
        self.api = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)

    def get_account_balance(self):
        account = self.api.get_account()
        return float(account.cash)

    def get_current_price(self, symbol):
        try:
            # Try to get latest quote from Alpaca
            quote = self.api.get_latest_quote(symbol)
            return float(quote.ask_price)
        except Exception as e:
            print(f"Alpaca quote failed: {e}")
            try:
                # Fallback to yfinance
                import yfinance as yf
                data = yf.download(symbol, period="1d", progress=False)
                price = data['Close'].iloc[-1]
                if hasattr(price, 'item'):
                    price = price.item()
                return float(price)
            except Exception as e2:
                print(f"YFinance fallback failed: {e2}")
                return 100.0  # Default fallback price

    def buy(self, symbol, qty):
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=int(qty),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        self.api.submit_order(order_data)

    def sell(self, symbol, qty):
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=int(qty),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        self.api.submit_order(order_data)

    def get_position_size(self, symbol):
        try:
            positions = self.api.get_all_positions()
            for pos in positions:
                if pos.symbol == symbol:
                    return float(pos.qty)
        except:
            pass
        return 0