from model import predict_price
from strategy import TradingStrategy
from data_fetcher import fetch_stock_data, preprocess_data


def backtest_strategy(symbol, start_date, end_date):
    """Run a simple backtest on historical data."""
    data = fetch_stock_data(symbol, start=start_date, end=end_date)
    data = preprocess_data(data)
    if len(data) < 60:
        raise ValueError("Not enough historical data to run the backtest.")

    strategy = TradingStrategy()
    capital = 10000.0
    positions = 0.0

    for i in range(60, len(data)):
        recent_data = data["Close"].iloc[i - 60:i].to_numpy()
        predicted_price = predict_price(strategy.model, strategy.scaler, recent_data)
        current_price = data["Close"].iloc[i]
        current_price = float(current_price.item() if hasattr(current_price, "item") else current_price)

        if predicted_price > current_price * 1.01 and positions == 0:
            positions = capital / current_price
            capital = 0.0
        elif predicted_price < current_price * 0.99 and positions > 0:
            capital = positions * current_price
            positions = 0.0

    last_price = data["Close"].iloc[-1]
    last_price = float(last_price.item() if hasattr(last_price, "item") else last_price)
    final_value = capital + positions * last_price
    return round(final_value, 2)


if __name__ == "__main__":
    result = backtest_strategy("AAPL", "2020-01-01", "2023-01-01")
    print(f"Final portfolio value: ${result}")