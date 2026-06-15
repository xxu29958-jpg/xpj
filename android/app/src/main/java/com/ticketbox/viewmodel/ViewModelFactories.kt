package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.data.repository.TagActions
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
            MonthlyStatsViewModel::class.java -> MonthlyStatsViewModel(repository, recurringRepository)
            StatsBudgetViewModel::class.java -> StatsBudgetViewModel(repository, budgetRepository)
            StatsReportsViewModel::class.java -> StatsReportsViewModel(reportsRepository)
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
fun incomePlanViewModelFactory(
    repository: IncomePlanActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return IncomePlanViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun debtGoalViewModelFactory(
    repository: ReportsActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtGoalViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun settingsViewModelFactory(
    repository: ExpenseRepository,
    settingsStore: LocalSettingsStore,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return SettingsViewModel(repository, settingsStore) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun categoryRulesViewModelFactory(
    ruleRepository: RuleRepository,
    repository: ExpenseRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return CategoryRulesViewModel(ruleRepository, repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun merchantAliasViewModelFactory(
    merchantRepository: MerchantRepository,
    repository: ExpenseRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return MerchantAliasViewModel(merchantRepository, repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun tagManagementViewModelFactory(
    tagRepository: TagActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return TagManagementViewModel(tagRepository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun appearanceViewModelFactory(
    settingsStore: LocalSettingsStore,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return AppearanceViewModel(settingsStore) as T
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

@Suppress("UNCHECKED_CAST")
fun outboxStatusViewModelFactory(
    outbox: OutboxRepository,
    expenseRepository: ExpenseRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return OutboxStatusViewModel(outbox, expenseRepository) as T
    }
}
