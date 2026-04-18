from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from config import ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL


class Broker:
    def __init__(self):
        self.api = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)

    def get_account_balance(self):
        account = self.api.get_account()
        return float(account.cash)

    def get_portfolio_value(self):
        try:
            account = self.api.get_account()
            portfolio_value = getattr(account, "portfolio_value", account.cash)
            return float(portfolio_value)
        except Exception as e:
            print(f"Unable to fetch portfolio value: {e}")
            return self.get_account_balance()

    def get_current_price(self, symbol):
        try:
            import yfinance as yf

            data = yf.download(symbol, period="5d", progress=False, auto_adjust=False)
            if hasattr(data, "columns") and getattr(data.columns, "nlevels", 1) > 1:
                data.columns = data.columns.get_level_values(0)
            price = data["Close"].iloc[-1]
            if hasattr(price, "item"):
                price = price.item()
            return float(price)
        except Exception as e:
            print(f"Price fetch failed for {symbol}: {e}")
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

    def get_position(self, symbol):
        symbol = str(symbol).upper()
        try:
            positions = self.api.get_all_positions()
            for pos in positions:
                if str(pos.symbol).upper() == symbol:
                    return {
                        "symbol": symbol,
                        "qty": float(pos.qty),
                        "entry_price": float(getattr(pos, "avg_entry_price", 0.0) or 0.0),
                        "market_value": float(getattr(pos, "market_value", 0.0) or 0.0),
                    }
        except Exception:
            pass
        return None

    def get_position_size(self, symbol):
        position = self.get_position(symbol)
        return float(position["qty"]) if position else 0

    def get_open_positions_count(self):
        try:
            return len(self.api.get_all_positions())
        except Exception as e:
            print(f"Unable to fetch open positions: {e}")
            return 0