package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.data.repository.DebtRepaymentQueries
import com.ticketbox.data.repository.ExpenseRepositoryBackgroundTaskActions
import com.ticketbox.data.repository.ExpenseFactActions
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
import com.ticketbox.domain.model.DebtListLens

@Suppress("UNCHECKED_CAST")
fun appViewModelFactory(
    repository: ExpenseRepository,
    settingsStore: TicketboxSettingsStore,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return AppViewModel(repository, settingsStore) as T
    }
}

/** [repositoryViewModelFactory] 的仓库打包（保持工厂签名在 detekt 参数门内）。 */
data class RepositoryViewModelRepositories(
    val repository: ExpenseRepository,
    val budgetRepository: BudgetActions? = null,
    val reportsRepository: ReportsActions? = null,
    val debtRepository: DebtActions? = null,
)

@Suppress("UNCHECKED_CAST")
fun repositoryViewModelFactory(
    repositories: RepositoryViewModelRepositories,
    onExpenseDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        val repository = repositories.repository
        return when (modelClass) {
            PendingViewModel::class.java -> PendingViewModel(
                repository = repository,
                enrichmentTaskReader = repository.pendingEnrichmentTasks,
                onDataChanged = onExpenseDataChanged,
            )
            LedgerViewModel::class.java -> LedgerViewModel(
                repository,
                checkNotNull(repositories.debtRepository) { "LedgerViewModel requires DebtActions for R13-6 capability" },
                onDataChanged = onExpenseDataChanged,
            )
            GlobalSearchViewModel::class.java -> GlobalSearchViewModel(repository)
            MonthlyStatsViewModel::class.java -> MonthlyStatsViewModel(repository)
            StatsBudgetViewModel::class.java -> StatsBudgetViewModel(repository, repositories.budgetRepository)
            StatsReportsViewModel::class.java -> StatsReportsViewModel(repositories.reportsRepository)
            else -> error("Unsupported ViewModel: ${modelClass.name}")
        } as T
    }
}

@Suppress("UNCHECKED_CAST")
fun budgetViewModelFactory(
    repository: BudgetActions,
    debts: DebtActions,
    onDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return BudgetViewModel(repository, debts, onDataChanged = onDataChanged) as T
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
    debts: DebtActions,
    onDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return IncomePlanViewModel(repository, debts, onDataChanged = onDataChanged) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun incomePlanEditViewModelFactory(
    repository: IncomePlanActions,
    debts: DebtActions,
    onDataChanged: () -> Unit = {},
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return IncomePlanEditViewModel(repository, debts, onDataChanged = onDataChanged) as T
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
fun debtViewModelFactory(
    repository: DebtActions,
    creation: com.ticketbox.data.repository.DebtCreationActions,
    lens: DebtListLens = DebtListLens.Ledger,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtListViewModel(repository, creation, lens) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun debtDetailViewModelFactory(
    repository: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtDetailViewModel(repository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun debtRepaymentHistoryViewModelFactory(
    repository: DebtRepaymentQueries,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtRepaymentHistoryViewModel(repository) as T
    }
}

// ADR-0049 P3b / ⑤c (slice ⑤c-2): 欠我的(应收) 只读发现面。只依赖窄接口 ReceivablesActions
// （DebtRepository 实现它），故无需碰其它 DebtActions 的测试 fake。
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
    debtRepository: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return CreateSpendingGoalViewModel(reportsRepository, debtRepository) as T
    }
}

@Suppress("UNCHECKED_CAST")
fun settingsViewModelFactory(
    repository: ExpenseRepository,
    settingsStore: TicketboxSettingsStore,
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
    settingsStore: TicketboxSettingsStore,
    images: com.ticketbox.data.repository.BackgroundImageRepository,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return AppearanceViewModel(settingsStore, images) as T
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

/**
 * A1: confirmed 事实/更正 Owner 的工厂。依赖窄接口 [ExpenseFactActions]
 * （生产由 ExpenseRepository 满足；测试用 fake）—— pending 编辑不经过这里。
 */
@Suppress("UNCHECKED_CAST")
fun expenseFactViewModelFactory(
    expenseId: Long,
    repository: ExpenseFactActions,
    initialExpense: com.ticketbox.domain.model.Expense? = null,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return ExpenseFactViewModel(expenseId, repository, initialExpense) as T
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
