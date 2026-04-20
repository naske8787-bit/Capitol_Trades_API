from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestBarRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from config import ALPACA_API_KEY, ALPACA_API_SECRET, CRYPTO_PAPER_ONLY
from data_fetcher import fetch_crypto_data, to_alpaca_symbol


class Broker:
    def __init__(self):
        if not ALPACA_API_KEY or not ALPACA_API_SECRET:
            raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_API_SECRET in the environment.")
        self.api = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=CRYPTO_PAPER_ONLY)
        self._data_client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)

    def get_account_balance(self):
        account = self.api.get_account()
        return float(account.cash)

    def get_portfolio_value(self):
        account = self.api.get_account()
        portfolio_value = getattr(account, "portfolio_value", account.cash)
        return float(portfolio_value)

    def get_current_price(self, symbol):
        alpaca_symbol = to_alpaca_symbol(symbol)
        try:
            bars = self._data_client.get_crypto_latest_bar(
                CryptoLatestBarRequest(symbol_or_symbols=alpaca_symbol)
            )
            bar = bars.get(alpaca_symbol)
            if bar is not None:
                return float(bar.close)
        except Exception as e:
            print(f"Alpaca crypto price fetch failed for {symbol}, falling back to yfinance: {e}")
        data = fetch_crypto_data(symbol, period="5d", interval="1h")
        if data.empty:
            raise RuntimeError(f"No price data returned for {symbol}")
        price = data["Close"].iloc[-1]
        return float(price.item() if hasattr(price, "item") else price)

    def buy(self, symbol, qty):
        order_data = MarketOrderRequest(
            symbol=to_alpaca_symbol(symbol),
            qty=round(float(qty), 6),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
        )
        self.api.submit_order(order_data)

    def sell(self, symbol, qty):
        order_data = MarketOrderRequest(
            symbol=to_alpaca_symbol(symbol),
            qty=round(float(qty), 6),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
        )
        self.api.submit_order(order_data)

    def get_position_size(self, symbol):
        normalized_symbol = to_alpaca_symbol(symbol)
        try:
            for position in self.api.get_all_positions():
                if str(position.symbol).upper() == normalized_symbol:
                    return float(position.qty)
        except Exception:
            pass
        return 0.0

    def get_open_positions_count(self):
        try:
            return len(self.api.get_all_positions())
        except Exception:
            return 0
