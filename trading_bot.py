"""Local paper-trading simulator; it does not place brokerage orders.

Run with:
    python trading_bot.py
    python trading_bot.py --buy AAPL 5 180 --prices AAPL=190
    python trading_bot.py --sell AAPL 2 190 --holdings AAPL=5@180 --prices AAPL=190
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from math import isfinite
from typing import Dict, List


def _validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol must not be empty.")
    return symbol.strip().upper()


def _validate_shares(shares: int) -> None:
    if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
        raise ValueError("Shares must be a positive whole number.")


def _validate_price(price: float) -> float:
    if (
        isinstance(price, bool)
        or not isinstance(price, (int, float))
        or not isfinite(price)
        or price <= 0
    ):
        raise ValueError("Price must be a finite number greater than zero.")
    return float(price)


@dataclass
class Position:
    symbol: str
    shares: int = 0
    avg_price: float = 0.0

    def market_value(self, price: float) -> float:
        value = self.shares * _validate_price(price)
        if not isfinite(value):
            raise ValueError("Position value must be finite.")
        return value

    def __str__(self) -> str:
        return f"{self.symbol}: {self.shares} shares @ ${self.avg_price:.2f}"


class TradingBot:
    def __init__(self, cash: float = 10_000.0):
        try:
            starting_cash = float(cash)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Starting cash must be a finite, non-negative number.") from error
        if not isfinite(starting_cash) or starting_cash < 0:
            raise ValueError("Starting cash must be a finite, non-negative number.")

        self.cash = starting_cash
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[str] = []

    def buy(self, symbol: str, shares: int, price: float) -> str:
        symbol = _validate_symbol(symbol)
        _validate_shares(shares)
        price = _validate_price(price)

        cost = shares * price
        if not isfinite(cost):
            raise ValueError("Trade value must be finite.")
        if cost > self.cash:
            raise ValueError(
                f"Not enough cash. Need ${cost:.2f}, but only ${self.cash:.2f} available."
            )

        existing = self.positions.get(symbol)
        if existing is None:
            updated_position = Position(symbol=symbol, shares=shares, avg_price=price)
        else:
            total_shares = existing.shares + shares
            total_cost = (existing.shares * existing.avg_price) + cost
            updated_position = Position(
                symbol=symbol,
                shares=total_shares,
                avg_price=total_cost / total_shares,
            )

        self.cash -= cost
        self.positions[symbol] = updated_position
        message = f"Bought {shares} shares of {symbol} at ${price:.2f}."
        self.trade_history.append(message)
        return message

    def sell(self, symbol: str, shares: int, price: float) -> str:
        symbol = _validate_symbol(symbol)
        _validate_shares(shares)
        price = _validate_price(price)

        existing = self.positions.get(symbol)
        if existing is None or existing.shares < shares:
            raise ValueError(f"Not enough shares of {symbol} to sell.")

        proceeds = shares * price
        updated_cash = self.cash + proceeds
        if not isfinite(proceeds) or not isfinite(updated_cash):
            raise ValueError("Trade value must be finite.")

        self.cash = updated_cash
        existing.shares -= shares

        if existing.shares == 0:
            del self.positions[symbol]

        message = f"Sold {shares} shares of {symbol} at ${price:.2f}."
        self.trade_history.append(message)
        return message

    def portfolio_value(self, prices: Dict[str, float]) -> float:
        total = self.cash
        for symbol, position in self.positions.items():
            if symbol not in prices:
                raise ValueError(f"Missing market price for {symbol}.")
            total += position.market_value(prices[symbol])
            if not isfinite(total):
                raise ValueError("Portfolio value must be finite.")
        return total

    def summary(self, prices: Dict[str, float]) -> str:
        net_worth = self.portfolio_value(prices)
        lines = [
            "=== Portfolio Summary ===",
            f"Cash: ${self.cash:.2f}",
            f"Net worth: ${net_worth:.2f}",
        ]

        if not self.positions:
            lines.append("No open positions.")
            return "\n".join(lines)

        lines.append("Positions:")
        for symbol, position in sorted(self.positions.items()):
            price = prices[symbol]
            market_value = position.market_value(price)
            lines.append(
                f"- {symbol}: {position.shares} shares @ ${position.avg_price:.2f} "
                f"(market ${price:.2f}, value ${market_value:.2f})"
            )

        return "\n".join(lines)

    def recent_trades(self, limit: int = 5) -> str:
        if not self.trade_history:
            return "No trades yet."
        return "\n".join(self.trade_history[-limit:])


def parse_price_map(raw: str) -> Dict[str, float]:
    if not isinstance(raw, str):
        raise ValueError("Prices must be provided as comma-separated SYMBOL=PRICE pairs.")
    if not raw.strip():
        return {}

    prices: Dict[str, float] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        symbol, separator, value = item.partition("=")
        symbol = symbol.strip().upper()
        if not separator or not symbol or not value.strip():
            raise ValueError(
                f"Invalid price entry {item!r}; expected SYMBOL=PRICE."
            )
        if symbol in prices:
            raise ValueError(f"Duplicate price entry for {symbol}.")
        try:
            prices[symbol] = _validate_price(float(value.strip()))
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Invalid price for {symbol}: {value.strip()!r}.") from error
    return prices


def parse_holding_map(raw: str) -> Dict[str, Position]:
    if not isinstance(raw, str):
        raise ValueError(
            "Holdings must be comma-separated SYMBOL=SHARES@AVG_PRICE entries."
        )
    if not raw.strip():
        return {}

    positions: Dict[str, Position] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        symbol, separator, holding = item.partition("=")
        symbol = _validate_symbol(symbol)
        shares_text, at_separator, average_price_text = holding.partition("@")
        if not separator or not at_separator or not shares_text or not average_price_text:
            raise ValueError(
                f"Invalid holding {item!r}; expected SYMBOL=SHARES@AVG_PRICE."
            )
        if symbol in positions:
            raise ValueError(f"Duplicate holding for {symbol}.")
        try:
            shares = int(shares_text)
            average_price = _validate_price(float(average_price_text))
            _validate_shares(shares)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"Invalid holding for {symbol}: {holding!r}.") from error
        positions[symbol] = Position(symbol, shares, average_price)
    return positions


def demo_run() -> TradingBot:
    bot = TradingBot(10_000)
    prices = {"AAPL": 185.25, "MSFT": 410.75, "NVDA": 118.60, "GOOG": 272.10}

    bot.buy("AAPL", 10, prices["AAPL"])
    bot.buy("MSFT", 5, prices["MSFT"])
    bot.sell("AAPL", 3, prices["AAPL"] * 1.03)
    bot.buy("NVDA", 20, prices["NVDA"])

    print("=== Trading Bot Demo ===")
    print(bot.summary(prices))
    print("\nRecent trades:")
    print(bot.recent_trades())
    return bot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local paper-trading simulator; no brokerage orders are placed."
    )
    parser.add_argument("--cash", type=float, default=10_000.0, help="Starting cash")
    parser.add_argument(
        "--prices",
        type=str,
        default="AAPL=185.25,MSFT=410.75,NVDA=118.60,GOOG=272.10",
        help="Comma-separated symbol=price pairs",
    )
    parser.add_argument(
        "--holdings",
        type=str,
        default="",
        help="Starting positions as comma-separated SYMBOL=SHARES@AVG_PRICE pairs",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--buy",
        nargs=3,
        metavar=("SYMBOL", "SHARES", "PRICE"),
        help="Simulate buying shares",
    )
    action.add_argument(
        "--sell",
        nargs=3,
        metavar=("SYMBOL", "SHARES", "PRICE"),
        help="Simulate selling shares",
    )
    args = parser.parse_args()

    try:
        bot = TradingBot(args.cash)
        bot.positions.update(parse_holding_map(args.holdings))
        prices = parse_price_map(args.prices)

        if args.buy:
            symbol, shares, price = args.buy
            print(bot.buy(symbol, int(shares), float(price)))
        elif args.sell:
            symbol, shares, price = args.sell
            print(bot.sell(symbol, int(shares), float(price)))
        else:
            demo_run()
            return

        print(bot.summary(prices))
    except (ValueError, OverflowError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
