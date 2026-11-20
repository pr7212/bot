class TradingBot:
    def __init__(self):
        self.expenses = []

    def add_expense(self, expense):
        self.expenses.append(expense)

    def calculate_total_spending(self):
        return sum(self.expenses)
