package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.ReportsActions

fun spendingGoalsViewModelFactory(
    reports: ReportsActions,
    edits: GoalEditActions,
    calendars: com.ticketbox.data.repository.LedgerCalendarReader? = null,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalsViewModel(reports, edits, calendars = calendars) as T
}

fun spendingGoalDetailViewModelFactory(
    reports: ReportsActions,
    edits: GoalEditActions,
    drafts: SpendingGoalEditDraftStore = SpendingGoalEditDraftStore(SavedStateHandle()),
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        SpendingGoalDetailViewModel(reports, edits, drafts) as T
}

fun spendingGoalEditDraftStoreFactory(): ViewModelProvider.Factory = viewModelFactory {
    initializer { SpendingGoalEditDraftStore(createSavedStateHandle()) }
}
