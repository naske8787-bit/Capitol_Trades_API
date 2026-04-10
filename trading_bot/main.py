from strategy import TradingStrategy
from broker import Broker
import time
from config import MAX_POSITIONS

def main():
    broker = Broker()
    strategy = TradingStrategy()

    symbols = ['AAPL', 'GOOGL', 'TSLA']  # Example symbols

    print("Trading bot started. Press Ctrl+C to stop.")
    
    while True:
        for symbol in symbols:
            try:
                signal = strategy.analyze_signal(symbol)
                print(f"{symbol}: {signal}")
                strategy.execute_trade(signal, symbol, broker)
                time.sleep(1)  # Rate limit
            except Exception as e:
                print(f"Error processing {symbol}: {e}")

        # Check every hour or so
        print("Waiting 1 hour before next check...")
        time.sleep(3600)

if __name__ == "__main__":
    main()