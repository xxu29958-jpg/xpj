package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDetailActions
import com.ticketbox.data.repository.DebtListActions
import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.data.repository.ExpenseRepositoryBackgroundTaskActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.ExpenseRepositorySettingsActions
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.ReceivablesActions
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.RepaymentDraftActions
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
    onExpenseDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return when (modelClass) {
            PendingViewModel::class.java -> PendingViewModel(repository, onDataChanged = onExpenseDataChanged)
            LedgerViewModel::class.java -> LedgerViewModel(repository, onDataChanged = onExpenseDataChanged)
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
    onDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return BudgetViewModel(repository, onDataChanged = onDataChanged) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun budgetAdviceViewModelFactory(
    repository: BudgetActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return BudgetAdviceViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun recurringViewModelFactory(
    repository: RecurringRepository,
    onDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return RecurringViewModel(repository, onDataChanged = onDataChanged) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun incomePlanViewModelFactory(
    repository: IncomePlanActions,
    onDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return IncomePlanViewModel(repository, onDataChanged = onDataChanged) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun debtGoalViewModelFactory(
    repository: ReportsActions,
    debts: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtGoalViewModel(repository, debts) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun debtViewModelFactory(
    repository: DebtListActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtListViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun debtDetailViewModelFactory(
    repository: DebtDetailActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtDetailViewModel(repository) as T
    }
}

// 欠我的 viewer-personal 应收只读面，只依赖窄接口 ReceivablesActions。
@Suppress("UNCHECKED_CAST")
fun receivablesViewModelFactory(
    repository: ReceivablesActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return ReceivablesViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun memberRepaymentProposalViewModelFactory(
    repository: DebtProposalActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return MemberRepaymentProposalViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun repaymentDraftInboxViewModelFactory(
    drafts: RepaymentDraftActions,
    debts: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return RepaymentDraftInboxViewModel(drafts, debts) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun createDebtGoalViewModelFactory(
    reportsRepository: ReportsActions,
    debtRepository: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return CreateDebtGoalViewModel(reportsRepository, debtRepository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun createSpendingGoalViewModelFactory(
    reportsRepository: ReportsActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return CreateSpendingGoalViewModel(reportsRepository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun settingsViewModelFactory(
    repository: ExpenseRepository,
    settingsStore: LocalSettingsStore,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return SettingsViewModel(ExpenseRepositorySettingsActions(repository), settingsStore) as T
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
fun myDevicesViewModelFactory(
    repository: LedgerRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return MyDevicesViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun recycleBinViewModelFactory(
    repository: LedgerRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return RecycleBinViewModel(repository) as T
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
        return BackgroundTasksViewModel(ExpenseRepositoryBackgroundTaskActions(repository)) as T
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
