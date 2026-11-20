import math
import unittest

from trading_bot import TradingBot, parse_holding_map, parse_price_map


class TradingBotTests(unittest.TestCase):
    def test_starting_cash_must_be_finite_and_non_negative(self):
        for cash in (-1, math.nan, math.inf, -math.inf):
            with self.subTest(cash=cash):
                with self.assertRaises(ValueError):
                    TradingBot(cash)

    def test_buy_rejects_invalid_price_without_changing_account(self):
        for price in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(price=price):
                bot = TradingBot(100)
                with self.assertRaises(ValueError):
                    bot.buy("XYZ", 1, price)
                self.assertEqual(bot.cash, 100)
                self.assertEqual(bot.positions, {})
                self.assertEqual(bot.trade_history, [])

    def test_sell_rejects_invalid_price_without_changing_account(self):
        for price in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(price=price):
                bot = TradingBot(100)
                bot.buy("XYZ", 2, 10)
                cash_before = bot.cash
                history_before = list(bot.trade_history)

                with self.assertRaises(ValueError):
                    bot.sell("XYZ", 1, price)

                self.assertEqual(bot.cash, cash_before)
                self.assertEqual(bot.positions["XYZ"].shares, 2)
                self.assertEqual(bot.trade_history, history_before)

    def test_buy_and_sell_update_average_price_and_portfolio_value(self):
        bot = TradingBot(1_000)
        bot.buy(" xyz ", 2, 10)
        bot.buy("XYZ", 2, 20)
        self.assertEqual(bot.positions["XYZ"].avg_price, 15)
        self.assertEqual(bot.portfolio_value({"XYZ": 25}), 1_040)

        bot.sell("xyz", 1, 25)
        self.assertEqual(bot.positions["XYZ"].shares, 3)
        self.assertEqual(bot.cash, 965)
        self.assertEqual(bot.portfolio_value({"XYZ": 25}), 1_040)

    def test_portfolio_value_requires_a_valid_quote_for_each_position(self):
        bot = TradingBot(100)
        bot.buy("XYZ", 1, 10)

        with self.assertRaisesRegex(ValueError, "Missing market price for XYZ"):
            bot.portfolio_value({})
        with self.assertRaises(ValueError):
            bot.summary({"XYZ": math.nan})

    def test_price_map_rejects_malformed_and_invalid_entries(self):
        for raw in ("XYZ", "=10", "XYZ=", "XYZ=nan", "XYZ=-1", "XYZ=10,xyz=11"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_price_map(raw)

    def test_price_map_normalizes_symbols_and_skips_empty_entries(self):
        self.assertEqual(
            parse_price_map(" xyz=10.5,,ABC=20,"),
            {"XYZ": 10.5, "ABC": 20.0},
        )

    def test_holding_map_parses_positions_and_rejects_invalid_entries(self):
        position = parse_holding_map(" xyz=2@10.5 ")["XYZ"]
        self.assertEqual((position.symbol, position.shares, position.avg_price), ("XYZ", 2, 10.5))

        for raw in ("XYZ", "XYZ=0@10", "XYZ=2@nan", "XYZ=2@10,xyz=3@11"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_holding_map(raw)


if __name__ == "__main__":
    unittest.main()
