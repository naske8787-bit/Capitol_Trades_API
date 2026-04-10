import pandas as pd
from strategy import TradingStrategy
from data_fetcher import fetch_stock_data, preprocess_data

def backtest_strategy(symbol, start_date, end_date):
    """Simple backtest on historical data."""
    data = fetch_stock_data(symbol, start=start_date, end=end_date)
    data = preprocess_data(data)

    strategy = TradingStrategy()
    capital = 10000
    positions = 0

    for i in range(60, len(data)):
        recent_data = data['Close'].iloc[i-60:i].values
        predicted_price = strategy.model.predict(...)  # Simplified, need to implement properly

        # Simulate signals
        if predicted_price > data['Close'].iloc[i] * 1.01:
            # Buy
            if positions == 0:
                positions = capital / data['Close'].iloc[i]
                capital = 0
        elif predicted_price < data['Close'].iloc[i] * 0.99:
            # Sell
            if positions > 0:
                capital = positions * data['Close'].iloc[i]
                positions = 0

    final_value = capital + positions * data['Close'].iloc[-1]
    return final_value

# Example usage
if __name__ == "__main__":
    result = backtest_strategy('AAPL', '2020-01-01', '2023-01-01')
    print(f"Final portfolio value: ${result}")