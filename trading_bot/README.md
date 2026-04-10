# Automated Stock Trading Bot

This Python project implements an automated stock trading bot using machine learning (LSTM model) and data from Capitol Trades API for sentiment analysis. It integrates with Alpaca for trade execution.

## Features
- Fetches stock data and Capitol Trades data
- Trains ML model for price prediction
- Executes trades based on signals
- Backtesting capabilities

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Set up API keys in `.env`
3. Train the model: Run `python train_model.py` (you may need to create this)
4. Run the bot: `python main.py`

## Disclaimer
Automated trading involves risk. Use paper trading first. Consult financial advisors.