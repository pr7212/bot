class Expense:
    def __init__(self, date, description, amount):
        self.date = date
        self.description = description
        self.amount = amount

    def __str__(self):
        return f'Expense: {self.description} - ${self.amount:.2f} on {self.date}'