# Automated Stock Trading Bot

This project contains a simple machine-learning trading bot that combines market data with Capitol Trades activity and sends paper trades through Alpaca.

## Features
- Fetches stock price history with `yfinance`
- Pulls recent Capitol Trades activity for simple sentiment signals
- Trains and loads an LSTM-based prediction model
- Supports smoke testing and basic backtesting

## Setup
1. `cd trading_bot`
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your Alpaca credentials
4. If model artifacts are missing, generate them with `python train.py`

## Useful commands
- Safe smoke test: `python test_bot.py`
- Backtest: `python backtest.py`
- Run the bot: `python main.py`
- Background run: `./run_bot.sh`

## Notes
- Use an Alpaca **paper trading** account first.
- `.env`, logs, PID files, and generated model artifacts should stay out of the PR.

## Disclaimer
Automated trading involves risk. Use paper trading first and review the logic before enabling any live execution.