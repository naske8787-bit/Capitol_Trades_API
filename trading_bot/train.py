from data_fetcher import fetch_stock_data, preprocess_data
from model import train_model

def main():
    symbol = 'AAPL'  # Example
    data = fetch_stock_data(symbol, period="5y")
    data = preprocess_data(data)
    model, scaler = train_model(data)
    print("Model trained and saved.")

if __name__ == "__main__":
    main()