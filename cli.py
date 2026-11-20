import sys
import os
import subprocess
import argparse
from expense_tracker import calculate_total_spending
from expense import Expense

def add_expense(description, amount, date=None):
    expense = Expense(description, amount, date)
    expenses.append(expense)
    print(f'Expense added: {expense}')

def view_expenses():
    expenses = Expense.objects.all()
    return render(request, 'expenses.html', {'expenses': expenses})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Trading Bot CLI')
    parser.add_argument('command', choices=['add', 'view'], help='Command to execute')
    parser.add_argument('description', help='Description of the expense')
    parser.add_argument('amount', type=float, help='Amount of the expense')
    parser.add_argument('--date', help='Date of the expense')

    args = parser.parse_args()

    if args.command == 'add':
        add_expense(args.description, args.amount, args.date)
    elif args.command == 'view':
        view_expenses()
