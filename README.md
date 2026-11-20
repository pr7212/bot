# Paper Trading Simulator

A small, local-only simulator for practicing share trades and tracking a
portfolio. It uses prices supplied by the user or the built-in demo values;
it does not fetch live market data, connect to a broker, or place real orders.
Each CLI invocation starts a new in-memory account and does not save state.

## Requirements

Python 3 with no third-party packages required.

## Run

Show the built-in demo:

```powershell
python trading_bot.py
```

Simulate a buy and value the portfolio at a supplied market price:

```powershell
python trading_bot.py --cash 10000 --buy AAPL 5 180 --prices AAPL=190
```

To sell, provide the starting position explicitly. `--cash` is the available
cash balance in addition to the value of those holdings:

```powershell
python trading_bot.py --cash 10000 --sell AAPL 2 190 --holdings AAPL=5@180 --prices AAPL=190
```

Prices must be finite and greater than zero. A quote must be provided for every
open position when the portfolio summary is calculated. Holdings use the
format `SYMBOL=SHARES@AVERAGE_PRICE`; multiple entries are comma-separated.

The `TradingBot` class can also be used directly for sequential trades:

```python
from trading_bot import TradingBot

bot = TradingBot(10_000)
bot.buy("AAPL", 5, 180)
bot.sell("AAPL", 2, 190)
print(bot.summary({"AAPL": 190}))
```

## Tests

Run the built-in unit tests:

```powershell
python -m unittest discover -v
```
