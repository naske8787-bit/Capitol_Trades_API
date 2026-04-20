from data_fetcher import fetch_quiver_data

def test_endpoint(name, endpoint):
    print(f"\nTesting {name} endpoint: {endpoint}")
    data = fetch_quiver_data(endpoint=endpoint)
    if data:
        print(f"Success: Received {len(data) if hasattr(data, '__len__') else 'some'} records.")
    else:
        print("Failed to fetch data or no data returned.")

def main():
    endpoints = [
        ("Congressional Trading (all)", "https://api.quiverquant.com/beta/historical/congresstrading/all"),
        ("Congressional Trading (AAPL)", "https://api.quiverquant.com/beta/historical/congresstrading/AAPL"),
        ("Senate Lobbying", "https://api.quiverquant.com/beta/historical/lobbying/senate"),
        ("House Trading (all)", "https://api.quiverquant.com/beta/historical/housetrading/all"),
        ("Corporate Lobbying", "https://api.quiverquant.com/beta/historical/lobbying/corp"),
    ]
    for name, endpoint in endpoints:
        test_endpoint(name, endpoint)

if __name__ == "__main__":
    main()
