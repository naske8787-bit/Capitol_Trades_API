import time

from broker import Broker
from config import CRYPTO_LOOP_INTERVAL_SECONDS, CRYPTO_WATCHLIST
from strategy import TradingStrategy


def main():
    broker = Broker()
    strategy = TradingStrategy()

    print("Crypto bot started in paper-trading mode. Press Ctrl+C to stop.")
    print(f"Watching: {', '.join(CRYPTO_WATCHLIST)}")
    print(
        f"Starting account snapshot: cash=${broker.get_account_balance():.2f}, "
        f"portfolio=${broker.get_portfolio_value():.2f}"
    )

    while True:
        for symbol in CRYPTO_WATCHLIST:
            try:
                signal = strategy.analyze_signal(symbol)
                analysis = strategy.last_analysis.get(symbol, {})
                print(
                    f"{symbol}: {signal} | "
                    f"trend={analysis.get('trend_strength_pct', 0.0):.2f}% | "
                    f"rsi={analysis.get('rsi', 0.0):.1f} | "
                    f"momentum={analysis.get('momentum_pct', 0.0):.2f}%"
                )
                strategy.execute_trade(signal, symbol, broker)
                time.sleep(1)
            except Exception as e:
                print(f"Error processing {symbol}: {e}")

        print(
            f"Portfolio snapshot: cash=${broker.get_account_balance():.2f}, "
            f"portfolio=${broker.get_portfolio_value():.2f}"
        )
        print(f"Waiting {CRYPTO_LOOP_INTERVAL_SECONDS} seconds before next cycle...")
        time.sleep(CRYPTO_LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
