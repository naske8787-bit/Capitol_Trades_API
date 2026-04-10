from strategy import TradingStrategy
from broker import Broker
import sys

print('Testing bot initialization...')
try:
    broker = Broker()
    strategy = TradingStrategy()
    print('Bot initialized successfully')
    print(f'Account balance: ${broker.get_account_balance()}')

    # Force a BUY signal for testing
    print('Forcing BUY signal for testing...')
    strategy.execute_trade('BUY', 'AAPL', broker)
    print('BUY executed - check Alpaca dashboard')

    # Check positions after trade
    import time
    time.sleep(2)
    positions = broker.api.get_all_positions()
    print(f'Positions after trade: {len(positions)}')
    for pos in positions:
        print(f'  {pos.symbol}: {pos.qty} shares')

except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()