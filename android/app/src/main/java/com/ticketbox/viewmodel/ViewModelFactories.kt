package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.security.SecureTokenStore

@Suppress("UNCHECKED_CAST")
fun appViewModelFactory(
    repository: ExpenseRepository,
    settingsStore: LocalSettingsStore,
    tokenStore: SecureTokenStore,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return AppViewModel(repository, settingsStore, tokenStore) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun repositoryViewModelFactory(
    repository: ExpenseRepository,
    recurringRepository: RecurringRepository,
    budgetRepository: BudgetActions? = null,
    reportsRepository: ReportsActions? = null,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return when (modelClass) {
            PendingViewModel::class.java -> PendingViewModel(repository)
            LedgerViewModel::class.java -> LedgerViewModel(repository)
            GlobalSearchViewModel::class.java -> GlobalSearchViewModel(repository)
            StatsViewModel::class.java -> StatsViewModel(repository, recurringRepository, budgetRepository, reportsRepository)
            else -> error("Unsupported ViewModel: ${modelClass.name}")
        } as T
    }
}

@Suppress("UNCHECKED_CAST")
fun budgetViewModelFactory(
    repository: BudgetActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return BudgetViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun recurringViewModelFactory(
    repository: RecurringRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return RecurringViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun settingsViewModelFactory(
    repository: ExpenseRepository,
    ruleRepository: RuleRepository,
    merchantRepository: MerchantRepository,
    settingsStore: LocalSettingsStore,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return SettingsViewModel(repository, ruleRepository, merchantRepository, settingsStore) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun expenseEditViewModelFactory(
    expenseId: Long,
    repository: ExpenseRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return ExpenseEditViewModel(expenseId, repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun ledgerSwitcherViewModelFactory(
    repository: LedgerRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return LedgerSwitcherViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun familyMembersViewModelFactory(
    repository: LedgerRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return FamilyMembersViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun joinFamilyLedgerViewModelFactory(
    repository: LedgerRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return JoinFamilyLedgerViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun billSplitViewModelFactory(
    expenseRepository: ExpenseRepository,
    ledgerRepository: LedgerRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return BillSplitViewModel(expenseRepository, ledgerRepository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun backgroundTasksViewModelFactory(
    repository: ExpenseRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return BackgroundTasksViewModel(repository) as T
    }
}
