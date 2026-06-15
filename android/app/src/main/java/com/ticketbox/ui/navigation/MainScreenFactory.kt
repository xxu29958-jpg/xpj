package com.ticketbox.ui.navigation

import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.TagRepository
import com.ticketbox.viewmodel.repositoryViewModelFactory as createRepositoryViewModelFactory

internal class MainScreenFactory(
    val repository: ExpenseRepository,
    val ledgerRepository: LedgerRepository,
    val recurringRepository: RecurringRepository,
    val budgetRepository: BudgetRepository,
    val reportsRepository: ReportsActions,
    val incomePlanRepository: IncomePlanActions,
    val debtRepository: DebtActions,
    val outboxRepository: OutboxRepository,
    val tagRepository: TagRepository,
    val settingsViewModelFactory: ViewModelProvider.Factory,
    val categoryRulesViewModelFactory: ViewModelProvider.Factory,
    val merchantAliasViewModelFactory: ViewModelProvider.Factory,
    val appearanceViewModelFactory: ViewModelProvider.Factory,
) {
    val repositoryViewModelFactory: ViewModelProvider.Factory = createRepositoryViewModelFactory(
        repository = repository,
        recurringRepository = recurringRepository,
        budgetRepository = budgetRepository,
        reportsRepository = reportsRepository,
    )
}
