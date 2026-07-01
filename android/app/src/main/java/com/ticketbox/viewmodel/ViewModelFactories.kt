package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.DashboardCardsActions
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.data.repository.ExpenseRepository
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
    // 轨道2 [P1]：StatsReportsViewModel 的还款待确认 badge 计数源（pending 还款草稿）。
    repaymentDrafts: RepaymentDraftActions? = null,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return when (modelClass) {
            PendingViewModel::class.java -> PendingViewModel(repository)
            LedgerViewModel::class.java -> LedgerViewModel(repository)
            GlobalSearchViewModel::class.java -> GlobalSearchViewModel(repository)
            MonthlyStatsViewModel::class.java -> MonthlyStatsViewModel(repository, recurringRepository)
            StatsBudgetViewModel::class.java -> StatsBudgetViewModel(repository, budgetRepository)
            StatsReportsViewModel::class.java -> StatsReportsViewModel(reportsRepository, repaymentDrafts)
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
fun debtViewModelFactory(
    repository: DebtActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DebtListViewModel(repository) as T
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
fun dashboardCardsViewModelFactory(
    repository: DashboardCardsActions,
): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return DashboardCardsViewModel(repository) as T
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
