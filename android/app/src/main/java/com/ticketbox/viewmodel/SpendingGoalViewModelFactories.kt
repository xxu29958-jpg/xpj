package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.repository.ReportsActions

fun spendingGoalsViewModelFactory(
    reports: ReportsActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalsViewModel(reports) as T
}

fun spendingGoalDetailViewModelFactory(
    reports: ReportsActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalDetailViewModel(reports) as T
}
