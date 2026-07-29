package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.ReportsActions

fun spendingGoalsViewModelFactory(
    reports: ReportsActions,
    debts: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalsViewModel(reports, debts) as T
}

fun spendingGoalDetailViewModelFactory(
    reports: ReportsActions,
    debts: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalDetailViewModel(reports, debts) as T
}
