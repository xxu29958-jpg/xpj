package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.ReportsActions

fun spendingGoalsViewModelFactory(
    reports: ReportsActions,
    edits: GoalEditActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalsViewModel(reports, edits) as T
}

fun spendingGoalDetailViewModelFactory(
    reports: ReportsActions,
    edits: GoalEditActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalDetailViewModel(reports, edits) as T
}
