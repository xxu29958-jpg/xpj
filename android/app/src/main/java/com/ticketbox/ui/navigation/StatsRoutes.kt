package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.BudgetScreen
import com.ticketbox.ui.screens.DebtGoalScreen
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.screens.RecurringScreen
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.viewmodel.BudgetViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.StatsBudgetViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.budgetViewModelFactory
import com.ticketbox.viewmodel.debtGoalViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.mergeStatsUiState
import com.ticketbox.viewmodel.recurringViewModelFactory

internal const val IncomePlanViewModelKey = "income-plans"
internal const val DebtGoalViewModelKey = "debt-goals"

@Composable
internal fun BudgetRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val budgetViewModel: BudgetViewModel = viewModel(
        factory = budgetViewModelFactory(screenFactory.budgetRepository),
    )
    val state by budgetViewModel.uiState.collectAsStateWithLifecycle()
    BudgetScreen(
        state = state,
        onRefresh = budgetViewModel::refresh,
        onPreviousMonth = budgetViewModel::previousMonth,
        onNextMonth = budgetViewModel::nextMonth,
        onTotalAmountChange = budgetViewModel::updateTotalAmount,
        onRolloverAmountChange = budgetViewModel::updateRolloverAmount,
        onNonMonthlyAmountChange = budgetViewModel::updateNonMonthlyAmount,
        onExcludedCategoriesChange = budgetViewModel::updateExcludedCategories,
        onCategoryRowChange = budgetViewModel::updateCategoryRow,
        onAddCategoryRow = budgetViewModel::addCategoryRow,
        onRemoveCategoryRow = budgetViewModel::removeCategoryRow,
        onSave = budgetViewModel::save,
        onBack = onBack,
    )
}

@Composable
internal fun RecurringRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val recurringViewModel: RecurringViewModel = viewModel(
        factory = recurringViewModelFactory(screenFactory.recurringRepository),
    )
    val state by recurringViewModel.uiState.collectAsStateWithLifecycle()
    RecurringScreen(
        state = state,
        onRefresh = recurringViewModel::refresh,
        onConfirmCandidate = recurringViewModel::confirmCandidate,
        onPause = recurringViewModel::pause,
        onResume = recurringViewModel::resume,
        onArchive = recurringViewModel::archive,
        onBack = onBack,
    )
}

@Composable
internal fun IncomePlanRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val incomePlanViewModel: IncomePlanViewModel = viewModel(
        key = IncomePlanViewModelKey,
        factory = incomePlanViewModelFactory(screenFactory.incomePlanRepository),
    )
    IncomePlanScreen(
        viewModel = incomePlanViewModel,
        currency = LocalCurrencyDisplay.current,
        onBack = onBack,
    )
}

@Composable
internal fun DebtGoalRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val debtGoalViewModel: DebtGoalViewModel = viewModel(
        key = DebtGoalViewModelKey,
        factory = debtGoalViewModelFactory(screenFactory.reportsRepository),
    )
    // overlay 在 open/close 间复用缓存 VM 且跨账本切换存活;每次(重新)进入都 reload
    // (先清旧账本的债务再拉),避免在新账本下短暂看到上一账本的欠款(账本隔离)。
    LaunchedEffect(Unit) { debtGoalViewModel.reload() }
    // 返回 / overlay 自带回退处理在 DebtGoalScreen 内（详情先收、再关 overlay）。
    DebtGoalScreen(
        viewModel = debtGoalViewModel,
        currency = LocalCurrencyDisplay.current,
        onBack = onBack,
    )
}

@Composable
internal fun StatsRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val monthlyStatsViewModel: MonthlyStatsViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val budgetViewModel: StatsBudgetViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val reportsViewModel: StatsReportsViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val monthlyState by monthlyStatsViewModel.uiState.collectAsStateWithLifecycle()
    val budgetState by budgetViewModel.uiState.collectAsStateWithLifecycle()
    val reportsState by reportsViewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(shellState.dashboardCardsRevision, monthlyState.ledgerReady) {
        if (shellState.dashboardCardsRevision > 0 && monthlyState.ledgerReady) {
            monthlyStatsViewModel.refresh()
            budgetViewModel.refresh(monthlyState.month, monthlyState.stats, force = true)
            reportsViewModel.refresh(monthlyState.month, monthlyState.selectedTag)
        }
    }

    LaunchedEffect(
        monthlyState.ledgerReady,
        monthlyState.activeLedgerId,
        monthlyState.month,
        monthlyState.selectedTag,
    ) {
        if (monthlyState.ledgerReady) {
            reportsViewModel.refresh(monthlyState.month, monthlyState.selectedTag)
        }
    }

    LaunchedEffect(
        monthlyState.ledgerReady,
        monthlyState.activeLedgerId,
        monthlyState.month,
        monthlyState.selectedTag,
        monthlyState.stats,
    ) {
        if (monthlyState.ledgerReady) {
            budgetViewModel.refresh(monthlyState.month, monthlyState.stats)
        }
    }

    val state = mergeStatsUiState(
        monthly = monthlyState,
        budget = budgetState,
        reports = reportsState,
    )

    StatsScreen(
        state = state,
        onMonthChange = monthlyStatsViewModel::setMonth,
        onTagChange = monthlyStatsViewModel::setTag,
        onRefresh = {
            monthlyStatsViewModel.refresh()
            budgetViewModel.refresh(monthlyState.month, monthlyState.stats, force = true)
            reportsViewModel.refresh(monthlyState.month, monthlyState.selectedTag)
        },
        onOpenBudget = shellState::openBudget,
        onOpenRecurring = shellState::openRecurring,
        onOpenIncomePlans = shellState::openIncomePlans,
        onOpenDebtGoals = shellState::openDebtGoals,
        // §三报表钻取:post 一次性请求(当前统计月+被点分类)并切到账本 tab,
        // LedgerRoute 的 LaunchedEffect 消费(取走即清)。
        onDrillToLedger = { category ->
            shellState.ledgerDrill.post(LedgerDrillRequest(month = monthlyState.month, category = category))
            shellState.selectBottomTab(BottomTab.Ledger.key)
        },
        // 轴3 粒度切换:VM 持粒度并重拉,UI selected 用服务端回显。
        onGranularityChange = reportsViewModel::setGranularity,
    )
}
