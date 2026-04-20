import time

from broker import Broker
from config import AUTO_RETRAIN_ENABLED, AUTO_RETRAIN_INTERVAL_HOURS, WATCHLIST
from performance_tracker import PerformanceTracker
from strategy import TradingStrategy
from train import retrain_models


def main():
    broker = Broker()
    strategy = TradingStrategy()
    tracker = PerformanceTracker()

    symbols = WATCHLIST
    last_retrain_ts = 0.0

    print("Trading bot started. Press Ctrl+C to stop.")
    startup_snapshot = tracker.record_equity_snapshot(broker, note="startup")
    print(
        "Starting portfolio snapshot: "
        f"value=${float(startup_snapshot['portfolio_value']):.2f}, "
        f"cash=${float(startup_snapshot['cash_balance']):.2f}, "
        f"positions={startup_snapshot['open_positions']}"
    )

    while True:
        now = time.time()

        # Auto-retrain on schedule
        if AUTO_RETRAIN_ENABLED:
            retrain_interval_secs = AUTO_RETRAIN_INTERVAL_HOURS * 3600
            if now - last_retrain_ts >= retrain_interval_secs:
                print(f"Auto-retraining models (every {AUTO_RETRAIN_INTERVAL_HOURS}h)...")
                retrain_models(symbols=symbols)
                # Flush cached models so strategy picks up the fresh weights
                strategy.model_cache.clear()
                last_retrain_ts = time.time()
                print("Auto-retrain complete. Resuming trading loop.")

        for symbol in symbols:
            try:
                signal = strategy.analyze_signal(symbol, broker=broker)
                analysis = strategy.last_analysis.get(symbol, {})
                market_flag = "OK" if analysis.get("market_favorable", True) else "WEAK"
                print(
                    f"{symbol}: {signal} | "
                    f"predicted_change={analysis.get('predicted_change_pct', 0.0):.2f}% | "
                    f"sentiment={analysis.get('sentiment', 0)} | "
                    f"trend={analysis.get('trend_strength_pct', 0.0):.2f}% | "
                    f"market={market_flag}"
                )

                trade_result = strategy.execute_trade(signal, symbol, broker)
                if trade_result:
                    cash_balance = broker.get_account_balance()
                    tracker.record_trade(
                        action=trade_result["action"],
                        symbol=trade_result["symbol"],
                        qty=trade_result["qty"],
                        price=trade_result["price"],
                        cash_balance=cash_balance,
                        analysis=analysis,
                        note="bot_execution",
                    )

                time.sleep(1)
            except Exception as e:
                print(f"Error processing {symbol}: {e}")

        cycle_snapshot = tracker.record_equity_snapshot(broker, note="hourly_cycle")
        print(
            "Portfolio snapshot: "
            f"value=${float(cycle_snapshot['portfolio_value']):.2f}, "
            f"cash=${float(cycle_snapshot['cash_balance']):.2f}, "
            f"positions={cycle_snapshot['open_positions']}"
        )
        print("Waiting 1 hour before next check...")
        time.sleep(3600)


if __name__ == "__main__":
    main()