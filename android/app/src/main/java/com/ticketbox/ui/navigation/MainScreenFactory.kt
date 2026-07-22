package com.ticketbox.ui.navigation

import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.CategoryPreferenceRepository
import com.ticketbox.data.repository.DebtRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.RepaymentDraftRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.TagRepository
import com.ticketbox.viewmodel.repositoryViewModelFactory as createRepositoryViewModelFactory

internal class MainScreenFactory(
    val repositories: MainFeatureRepositories,
    val viewModelFactories: MainScreenViewModelFactories,
) {
    val repository: ExpenseRepository get() = repositories.repository
    val ledgerRepository: LedgerRepository get() = repositories.ledgerRepository
    val recurringRepository: RecurringRepository get() = repositories.recurringRepository
    val budgetRepository: BudgetRepository get() = repositories.budgetRepository
    val reportsRepository: ReportsActions get() = repositories.reportsRepository
    val incomePlanRepository: IncomePlanActions get() = repositories.incomePlanRepository
    val debtRepository: DebtRepository get() = repositories.debtRepository
    val repaymentDraftRepository: RepaymentDraftRepository get() = repositories.repaymentDraftRepository
    val outboxRepository: OutboxRepository get() = repositories.outboxRepository
    val tagRepository: TagRepository get() = repositories.tagRepository
    val categoryPreferenceRepository: CategoryPreferenceRepository
        get() = repositories.categoryPreferenceRepository
    val settingsViewModelFactory: ViewModelProvider.Factory get() = viewModelFactories.settingsViewModelFactory
    val categoryRulesViewModelFactory: ViewModelProvider.Factory get() =
        viewModelFactories.categoryRulesViewModelFactory
    val merchantAliasViewModelFactory: ViewModelProvider.Factory get() =
        viewModelFactories.merchantAliasViewModelFactory
    val appearanceViewModelFactory: ViewModelProvider.Factory get() = viewModelFactories.appearanceViewModelFactory

    val repositoryViewModelFactory: ViewModelProvider.Factory = createRepositoryViewModelFactory(
        repository = repositories.repository,
        recurringRepository = repositories.recurringRepository,
        budgetRepository = repositories.budgetRepository,
        reportsRepository = repositories.reportsRepository,
    )

    fun repositoryViewModelFactory(
        onExpenseDataChanged: () -> Unit,
    ): ViewModelProvider.Factory = createRepositoryViewModelFactory(
        repository = repositories.repository,
        recurringRepository = repositories.recurringRepository,
        budgetRepository = repositories.budgetRepository,
        reportsRepository = repositories.reportsRepository,
        onExpenseDataChanged = onExpenseDataChanged,
    )
}

internal data class MainFeatureRepositories(
    val repository: ExpenseRepository,
    val ledgerRepository: LedgerRepository,
    val recurringRepository: RecurringRepository,
    val budgetRepository: BudgetRepository,
    val reportsRepository: ReportsActions,
    val incomePlanRepository: IncomePlanActions,
    val debtRepository: DebtRepository,
    val repaymentDraftRepository: RepaymentDraftRepository,
    val outboxRepository: OutboxRepository,
    val tagRepository: TagRepository,
    val categoryPreferenceRepository: CategoryPreferenceRepository,
)

internal data class MainScreenViewModelFactories(
    val settingsViewModelFactory: ViewModelProvider.Factory,
    val categoryRulesViewModelFactory: ViewModelProvider.Factory,
    val merchantAliasViewModelFactory: ViewModelProvider.Factory,
    val appearanceViewModelFactory: ViewModelProvider.Factory,
)
