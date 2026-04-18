from config import BUY_THRESHOLD_PCT, SELL_THRESHOLD_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from data_fetcher import fetch_stock_data, preprocess_data
from model import load_trained_model, predict_price


def _max_drawdown(values):
    peak = None
    max_drawdown = 0.0
    for value in values:
        peak = value if peak is None else max(peak, value)
        if peak:
            drawdown = (value - peak) / peak
            max_drawdown = min(max_drawdown, drawdown)
    return abs(max_drawdown) * 100


def backtest_strategy(symbol, start_date, end_date, initial_capital=10000.0):
    """Backtest the current model + trend-filter strategy on historical data."""
    data = preprocess_data(fetch_stock_data(symbol, start=start_date, end=end_date, use_cache=False))
    if len(data) < 60:
        raise ValueError("Not enough historical data to run the backtest.")

    model, scaler = load_trained_model(symbol=symbol)
    close = data["Close"].astype(float)
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    momentum_5d = close.pct_change(5).fillna(0.0)

    capital = float(initial_capital)
    shares = 0.0
    entry_price = None
    equity_curve = []
    completed_trades = []

    for i in range(60, len(data)):
        current_price = float(close.iloc[i])
        recent_data = close.iloc[i - 60:i].to_numpy()
        predicted_price = predict_price(model, scaler, recent_data)
        predicted_change = (predicted_price - current_price) / current_price
        trend_confirmation = bool(sma20.iloc[i] > sma50.iloc[i] and current_price > sma20.iloc[i])
        positive_momentum = bool(momentum_5d.iloc[i] >= BUY_THRESHOLD_PCT)

        if shares > 0:
            should_sell = (
                current_price <= entry_price * (1 - STOP_LOSS_PCT)
                or current_price >= entry_price * (1 + TAKE_PROFIT_PCT)
                or (
                    predicted_change <= -SELL_THRESHOLD_PCT
                    and (not trend_confirmation or momentum_5d.iloc[i] < 0)
                )
            )
            if should_sell:
                capital = shares * current_price
                pnl = capital - initial_capital if not completed_trades else capital - completed_trades[-1]["equity_after_trade"]
                completed_trades.append(
                    {
                        "action": "SELL",
                        "price": current_price,
                        "predicted_change_pct": predicted_change * 100,
                        "equity_after_trade": capital,
                        "pnl": pnl,
                    }
                )
                shares = 0.0
                entry_price = None
        else:
            should_buy = predicted_change >= BUY_THRESHOLD_PCT and trend_confirmation and positive_momentum
            if should_buy:
                shares = capital / current_price
                entry_price = current_price
                completed_trades.append(
                    {
                        "action": "BUY",
                        "price": current_price,
                        "predicted_change_pct": predicted_change * 100,
                        "equity_after_trade": capital,
                        "pnl": 0.0,
                    }
                )
                capital = 0.0

        equity_curve.append(capital + shares * current_price)

    final_price = float(close.iloc[-1])
    final_value = capital + shares * final_price
    buy_and_hold_value = initial_capital * (final_price / float(close.iloc[60]))

    return {
        "symbol": symbol.upper(),
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round(((final_value - initial_capital) / initial_capital) * 100, 2),
        "buy_and_hold_value": round(buy_and_hold_value, 2),
        "buy_and_hold_return_pct": round(((buy_and_hold_value - initial_capital) / initial_capital) * 100, 2),
        "max_drawdown_pct": round(_max_drawdown(equity_curve), 2),
        "signals_executed": len(completed_trades),
    }


if __name__ == "__main__":
    result = backtest_strategy("AAPL", "2020-01-01", "2023-01-01")
    print("=== Strategy Backtest Summary ===")
    print(f"Symbol:                 {result['symbol']}")
    print(f"Period:                 {result['start_date']} to {result['end_date']}")
    print(f"Initial capital:        ${result['initial_capital']:.2f}")
    print(f"Final portfolio value:  ${result['final_value']:.2f}")
    print(f"Strategy return:        {result['total_return_pct']:.2f}%")
    print(f"Buy & hold return:      {result['buy_and_hold_return_pct']:.2f}%")
    print(f"Max drawdown:           {result['max_drawdown_pct']:.2f}%")
    print(f"Signals executed:       {result['signals_executed']}")