def view_expenses(request):
    expenses = Expense.objects.all()
    return render(request, 'expenses.html', {'expenses': expenses})