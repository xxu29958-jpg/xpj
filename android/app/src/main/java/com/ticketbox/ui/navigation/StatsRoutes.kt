package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.BudgetScreen
import com.ticketbox.ui.screens.CreateDebtGoalScreen
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.screens.DebtGoalScreen
import com.ticketbox.ui.screens.DebtListScreen
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.screens.RecurringScreen
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.viewmodel.BudgetViewModel
import com.ticketbox.viewmodel.CreateDebtGoalViewModel
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.DebtListViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.StatsBudgetViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.budgetViewModelFactory
import com.ticketbox.viewmodel.createDebtGoalViewModelFactory
import com.ticketbox.viewmodel.debtDetailViewModelFactory
import com.ticketbox.viewmodel.debtGoalViewModelFactory
import com.ticketbox.viewmodel.debtViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.mergeStatsUiState
import com.ticketbox.viewmodel.recurringViewModelFactory

internal const val IncomePlanViewModelKey = "income-plans"
internal const val DebtGoalViewModelKey = "debt-goals"
internal const val CreateDebtGoalViewModelKey = "create-debt-goal"
internal const val DebtListViewModelKey = "debts"
internal const val DebtDetailViewModelKey = "debt-detail"

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
    val createViewModel: CreateDebtGoalViewModel = viewModel(
        key = CreateDebtGoalViewModelKey,
        factory = createDebtGoalViewModelFactory(
            screenFactory.reportsRepository,
            screenFactory.debtRepository,
        ),
    )
    // overlay 在 open/close 间复用缓存 VM 且跨账本切换存活;每次(重新)进入都 reload
    // (先清旧账本的债务再拉),避免在新账本下短暂看到上一账本的欠款(账本隔离)。
    LaunchedEffect(Unit) { debtGoalViewModel.reload() }
    val currency = LocalCurrencyDisplay.current
    // 新建还债目标是 overlay 内的子页（与列表/详情互斥渲染）：showCreate 切换,各屏自带
    // BackHandler（互斥 if/else 故同一时刻只有一个生效）。返回回到目标列表,创建成功后
    // 关闭子页并让目标列表重拉。
    var showCreate by rememberSaveable { mutableStateOf(false) }
    if (showCreate) {
        CreateDebtGoalScreen(
            viewModel = createViewModel,
            currency = currency,
            onBack = { showCreate = false },
            onCreated = {
                showCreate = false
                debtGoalViewModel.reload()
            },
        )
    } else {
        // 返回 / overlay 自带回退处理在 DebtGoalScreen 内（详情先收、再关 overlay）。
        DebtGoalScreen(
            viewModel = debtGoalViewModel,
            currency = currency,
            onBack = onBack,
            onCreate = { showCreate = true },
        )
    }
}

@Composable
internal fun DebtRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val debtListViewModel: DebtListViewModel = viewModel(
        key = DebtListViewModelKey,
        factory = debtViewModelFactory(screenFactory.debtRepository),
    )
    val detailViewModel: DebtDetailViewModel = viewModel(
        key = DebtDetailViewModelKey,
        factory = debtDetailViewModelFactory(screenFactory.debtRepository),
    )
    // overlay 复用缓存 VM 且跨账本切换存活;每次(重新)进入都 reload(先清旧账本的欠款再拉),
    // 避免在新账本下短暂看到上一账本的欠款(账本隔离;与 DebtGoalRoute 同构)。
    LaunchedEffect(Unit) { debtListViewModel.reload() }
    val currency = LocalCurrencyDisplay.current
    // 欠款详情是 overlay 内的子页(与列表互斥渲染,各屏自带 BackHandler):点击列表行进入详情,
    // 返回回到列表(顺手让列表重拉以反映详情里记的账)。详情 VM 是单例(常量 key),每次进入用
    // loadDebt 重拉而非复用陈旧折叠(与 DebtGoalRoute 的 reload 同构)。
    var detailDebtId by rememberSaveable { mutableStateOf<String?>(null) }
    val openDebtId = detailDebtId
    if (openDebtId != null) {
        LaunchedEffect(openDebtId) { detailViewModel.loadDebt(openDebtId) }
        DebtDetailScreen(
            viewModel = detailViewModel,
            currency = currency,
            onBack = {
                detailDebtId = null
                debtListViewModel.refresh()
            },
        )
    } else {
        DebtListScreen(
            viewModel = debtListViewModel,
            currency = currency,
            onBack = onBack,
            onOpenDebt = { detailDebtId = it.publicId },
        )
    }
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

    val state = mergeStatsUiState(monthly = monthlyState, budget = budgetState, reports = reportsState)

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
        onOpenDebts = shellState::openDebts,
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
