from config import TRAINING_SYMBOLS
from data_fetcher import fetch_stock_data, preprocess_data
from model import train_model


def main():
    for symbol in TRAINING_SYMBOLS:
        print(f"Training model for {symbol}...")
        data = fetch_stock_data(symbol, period="5y")
        data = preprocess_data(data)
        if len(data) < 60:
            print(f"Skipping {symbol}: not enough historical data.")
            continue

        train_model(data, symbol=symbol)
        print(f"Model trained and saved for {symbol}.")


if __name__ == "__main__":
    main()