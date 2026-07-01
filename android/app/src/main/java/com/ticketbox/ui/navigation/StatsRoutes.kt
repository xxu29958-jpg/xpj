package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import androidx.activity.compose.ManagedActivityResultLauncher
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.mascot.rememberMascotController
import com.ticketbox.ui.screens.BudgetScreen
import com.ticketbox.ui.screens.BudgetScreenActions
import com.ticketbox.ui.screens.CreateDebtGoalScreen
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.screens.DebtGoalCelebrationOverlay
import com.ticketbox.ui.screens.DebtGoalScreen
import com.ticketbox.ui.screens.DebtListScreen
import com.ticketbox.ui.screens.DebtSettleCelebrationOverlay
import com.ticketbox.ui.screens.IncomePlanScreen
import com.ticketbox.ui.screens.ReceivablesScreen
import com.ticketbox.ui.screens.RecurringScreen
import com.ticketbox.ui.screens.RepaymentDraftInboxScreen
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.upload.prepareScreenshotUpload
import com.ticketbox.viewmodel.BudgetViewModel
import com.ticketbox.viewmodel.CreateDebtGoalViewModel
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.DebtListViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.ReceivablesViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.RepaymentDraftInboxViewModel
import com.ticketbox.viewmodel.StatsBudgetViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.budgetViewModelFactory
import com.ticketbox.viewmodel.createDebtGoalViewModelFactory
import com.ticketbox.viewmodel.debtDetailViewModelFactory
import com.ticketbox.viewmodel.debtGoalViewModelFactory
import com.ticketbox.viewmodel.debtViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.memberRepaymentProposalViewModelFactory
import com.ticketbox.viewmodel.mergeStatsUiState
import com.ticketbox.viewmodel.receivablesViewModelFactory
import com.ticketbox.viewmodel.recurringViewModelFactory
import com.ticketbox.viewmodel.repaymentDraftInboxViewModelFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal const val IncomePlanViewModelKey = "income-plans"
internal const val DebtGoalViewModelKey = "debt-goals"
internal const val CreateDebtGoalViewModelKey = "create-debt-goal"
internal const val DebtListViewModelKey = "debts"
internal const val ReceivablesViewModelKey = "receivables"
internal const val DebtDetailViewModelKey = "debt-detail"
internal const val MemberRepaymentProposalViewModelKey = "member-repayment-proposal"
internal const val DebtGoalLinkedDetailViewModelKey = "debt-goal-linked-detail"
internal const val DebtGoalLinkedProposalViewModelKey = "debt-goal-linked-proposal"
// ⑤b-2: 应收(欠我的)的详情子页用自己的一组单例 VM（与 DebtRoute 的 debt-detail / member-repayment-
// proposal 隔离），避免两个 overlay 共享同一实例的庆祝去重 / 上一笔 status 跨面串扰。
internal const val ReceivablesDetailViewModelKey = "receivables-detail"
internal const val ReceivablesProposalViewModelKey = "receivables-proposal"
internal const val RepaymentDraftInboxViewModelKey = "repayment-draft-inbox"

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
        actions = BudgetScreenActions(
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
        ),
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
    val routeModels = rememberDebtGoalRouteViewModels(screenFactory)
    // overlay 在 open/close 间复用缓存 VM 且跨账本切换存活;每次(重新)进入都 refresh(clearStale=true)
    // (先清旧账本的债务再拉),避免在新账本下短暂看到上一账本的欠款(账本隔离)。
    LaunchedEffect(Unit) { routeModels.debtGoal.refresh(clearStale = true) }
    val currency = LocalCurrencyDisplay.current
    // 新建还债目标是 overlay 内的子页（与列表/详情互斥渲染）：showCreate 切换,各屏自带
    // BackHandler（互斥 if/else 故同一时刻只有一个生效）。返回回到目标列表,创建成功后
    // 关闭子页并让目标列表重拉。
    var showCreate by rememberSaveable { mutableStateOf(false) }
    var linkedDebtId by rememberSaveable { mutableStateOf<String?>(null) }
    val openLinkedDebtId = linkedDebtId
    if (showCreate) {
        CreateDebtGoalScreen(
            viewModel = routeModels.createGoal,
            currency = currency,
            onBack = { showCreate = false },
            onCreated = {
                showCreate = false
                routeModels.debtGoal.refresh(clearStale = true)
            },
        )
    } else if (openLinkedDebtId != null) {
        DebtDetailHost(
            openDebtId = openLinkedDebtId,
            detailViewModel = routeModels.linkedDetail,
            proposalViewModel = routeModels.linkedProposal,
            currency = currency,
            onBack = {
                linkedDebtId = null
                routeModels.debtGoal.refresh()
            },
        )
    } else {
        // §6.6 计划达成撒花：在 DebtGoalScreen 之上叠一层浮层（与 DebtRoute 的单笔两清浮层同构）。mascot
        // controller 是路由层关注点；celebration 由纯成员计划跨「未达成→达成」边沿产出（只读服务端 evaluation_state）。
        val mascot = rememberMascotController()
        val celebration by routeModels.debtGoal.celebration.collectAsStateWithLifecycle()
        // 离屏（切到创建子页 / 关 overlay）时丢弃未消费的撒花信号——浮层动画(~3.8s)中途离开会取消其 consume，
        // 单例 VM 持有的旧信号否则泄漏到下次进入误撒花（镜像 DebtRoute 的 DisposableEffect）。
        DisposableEffect(Unit) { onDispose { routeModels.debtGoal.consumeCelebration() } }
        Box(modifier = Modifier.fillMaxSize()) {
            // 返回 / overlay 自带回退处理在 DebtGoalScreen 内（详情先收、再关 overlay）。
            DebtGoalScreen(
                viewModel = routeModels.debtGoal,
                currency = currency,
                onBack = onBack,
                onCreate = { showCreate = true },
                onOpenLinkedDebt = { linkedDebtId = it },
            )
            DebtGoalCelebrationOverlay(
                celebration = celebration,
                mascot = mascot,
                onConsume = routeModels.debtGoal::consumeCelebration,
            )
        }
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
    // ADR-0049 §3.2 (slice 8d): 成员欠款的 proposal 收发箱 VM,与详情 VM 同为 overlay 内单例(常量 key),
    // 详情屏在加载到成员欠款时用 loadProposals 拉取(见 DebtDetailScreen 内 LaunchedEffect)。
    val proposalViewModel: MemberRepaymentProposalViewModel = viewModel(
        key = MemberRepaymentProposalViewModelKey,
        factory = memberRepaymentProposalViewModelFactory(screenFactory.debtRepository.proposals),
    )
    val context = LocalContext.current
    val parseScope = rememberCoroutineScope()
    val debtBillPicker = rememberDebtBillImageLauncher(debtListViewModel, context, parseScope)
    val openDebtBillPicker = {
        debtBillPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
    }
    // overlay 复用缓存 VM 且跨账本切换存活;每次(重新)进入都 reload(先清旧账本的欠款再拉),
    // 避免在新账本下短暂看到上一账本的欠款(账本隔离;与 DebtGoalRoute 同构)。
    LaunchedEffect(Unit) { debtListViewModel.reload() }
    val currency = LocalCurrencyDisplay.current
    // 欠款详情是 overlay 内的子页(与列表互斥渲染,各屏自带 BackHandler):点击列表行进入详情,
    // 返回回到列表(顺手让列表重拉以反映详情里记的账)。详情 VM 是单例(常量 key),每次进入用
    // loadDebt 重拉而非复用陈旧折叠(与 DebtGoalRoute 的 reload 同构)。详情子页 + 两清浮层的接线
    // 抽到共享的 [DebtDetailHost]（跨账本应收 ⑤b-2 复用同一套）。
    var detailDebtId by rememberSaveable { mutableStateOf<String?>(null) }
    val openDebtId = detailDebtId
    if (openDebtId != null) {
        DebtDetailHost(
            openDebtId = openDebtId,
            detailViewModel = detailViewModel,
            proposalViewModel = proposalViewModel,
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
            onParseBillImage = openDebtBillPicker,
        )
    }
}

@Composable
private fun rememberDebtBillImageLauncher(
    viewModel: DebtListViewModel,
    context: Context,
    scope: CoroutineScope,
): ManagedActivityResultLauncher<PickVisualMediaRequest, Uri?> =
    rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        if (!viewModel.markBillParsePreparing()) return@rememberLauncherForActivityResult
        scope.launch {
            val selected = withContext(Dispatchers.IO) { context.prepareScreenshotUpload(uri) }
            if (selected == null) {
                viewModel.billParsePreparationFailed()
                return@launch
            }
            viewModel.parseDebtBillImage(
                fileName = selected.fileName,
                contentType = selected.contentType,
                bytes = selected.bytes,
            )
        }
    }

/**
 * 欠款详情子页 + 两清庆祝浮层的接线，[DebtRoute]（同账本欠款列表）与 [ReceivablesRoute]（跨账本应收
 * ⑤b-2）共用：两个 overlay 的「列表 → 详情」结构完全一致，抽出避免重复那段微妙的 mascot / celebration /
 * dispose 接线，并让两个路由各自的函数保持短小。详情 VM 与 proposal VM 由调用方按自己的常量 key 创建后
 * 传入（两面各持一份实例，互不串扰）。
 *
 * §5（slice 8e-4）两清庆祝叠在详情屏之上（避免顶破 [DebtDetailScreen] 的 LongMethod，且天然覆盖整屏）；
 * mascot controller 是路由层关注点（§5.4 第一个真实 mascot emit 点）。[DisposableEffect] 在详情屏离开
 * （返回 / 切到另一笔）时丢弃未消费的庆祝信号——浮层动画(~3.8s)中途返回会取消其 consume，单例 VM 持有的
 * 旧信号否则会泄漏到下一笔欠款误撒花；dispose 先于下一笔 compose，无闪烁（对抗审 P2）。
 */
@Composable
private fun DebtDetailHost(
    openDebtId: String,
    detailViewModel: DebtDetailViewModel,
    proposalViewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    LaunchedEffect(openDebtId) { detailViewModel.loadDebt(openDebtId) }
    val mascot = rememberMascotController()
    val celebration by detailViewModel.celebration.collectAsStateWithLifecycle()
    DisposableEffect(openDebtId) { onDispose { detailViewModel.consumeCelebration() } }
    Box(modifier = Modifier.fillMaxSize()) {
        DebtDetailScreen(
            viewModel = detailViewModel,
            proposalViewModel = proposalViewModel,
            currency = currency,
            onBack = onBack,
        )
        DebtSettleCelebrationOverlay(
            celebration = celebration,
            mascot = mascot,
            onConsume = detailViewModel::consumeCelebration,
        )
    }
}

/**
 * ADR-0049 P3b / ⑤c+⑤b-2: 欠我的(应收) —— creditor 发现面（⑤c-2 列表）+ 跨账本 creditor 确认入口
 * （⑤b-2 详情子页）。VM 是 overlay 内单例（常量 key），跨账本切换存活；应收是**账户作用域**（跨账本）、
 * 与活跃账本无关，故不像 [DebtRoute] 按账本清旧数据，只在每次（重新）进入时 [ReceivablesViewModel.refresh]
 * 拉最新。
 *
 * ⑤b-2 把 ⑤c-2 的「只读非链接」反转为可点进详情：翻 `DEBT_ROLLOUT` 后债务人可对跨账本拆账债发起还款
 * proposal，债权人此前在 Android 无任何确认路径（详情只从账本作用域的 [DebtRoute] 列表进、跨账本债不在
 * 其中）。这里给应收行加 tap → 跨账本 debt detail（与列表互斥渲染的子页，复用 [DebtDetailHost]），详情走
 * §5.2 participant-scoped 路径：creditor 在 [DebtDetailScreen] 的 proposal 收发箱确认/拒绝对方的还款。详情
 * VM 用自己的一组 key（[ReceivablesDetailViewModelKey] / [ReceivablesProposalViewModelKey]），与 DebtRoute
 * 隔离。返回回到列表并 refresh（确认后那笔应收已 cleared，沉降到列表底部）。
 */
@Composable
internal fun ReceivablesRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val viewModel: ReceivablesViewModel = viewModel(
        key = ReceivablesViewModelKey,
        factory = receivablesViewModelFactory(screenFactory.debtRepository),
    )
    val detailViewModel: DebtDetailViewModel = viewModel(
        key = ReceivablesDetailViewModelKey,
        factory = debtDetailViewModelFactory(screenFactory.debtRepository),
    )
    val proposalViewModel: MemberRepaymentProposalViewModel = viewModel(
        key = ReceivablesProposalViewModelKey,
        factory = memberRepaymentProposalViewModelFactory(screenFactory.debtRepository.proposals),
    )
    LaunchedEffect(Unit) { viewModel.refresh() }
    val currency = LocalCurrencyDisplay.current
    var detailDebtId by rememberSaveable { mutableStateOf<String?>(null) }
    val openDebtId = detailDebtId
    if (openDebtId != null) {
        DebtDetailHost(
            openDebtId = openDebtId,
            detailViewModel = detailViewModel,
            proposalViewModel = proposalViewModel,
            currency = currency,
            onBack = {
                detailDebtId = null
                viewModel.refresh()
            },
        )
    } else {
        ReceivablesScreen(
            viewModel = viewModel,
            onOpenReceivable = { detailDebtId = it.publicId },
            onBack = onBack,
        )
    }
}

/**
 * ADR-0049 §杠杆③ (slice 3a): NLS 还款捕获复核箱二级页（规划面）。VM 同时拿还款草稿仓库与欠款仓库
 * （选债确认要列 open 外部手动欠款）。overlay 复用缓存 VM 且跨账本存活，故进入时 [reload] 先清旧账本残留。
 */
@Composable
internal fun RepaymentDraftRoute(
    screenFactory: MainScreenFactory,
    focusedDraftPublicId: String? = null,
    onFocusConsumed: () -> Unit = {},
    onBack: () -> Unit,
) {
    val launchFocusedDraftPublicId = remember { focusedDraftPublicId }
    val viewModel: RepaymentDraftInboxViewModel = viewModel(
        key = RepaymentDraftInboxViewModelKey,
        factory = repaymentDraftInboxViewModelFactory(
            drafts = screenFactory.repaymentDraftRepository,
            debts = screenFactory.debtRepository,
        ),
    )
    LaunchedEffect(Unit) {
        viewModel.reload(launchFocusedDraftPublicId)
        onFocusConsumed()
    }
    RepaymentDraftInboxScreen(
        viewModel = viewModel,
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
            // P4 stale-refresh: settings can change stats-relevant data while this VM
            // persists (dashboard cards; tag delete/rename/merge bumps the same
            // signal). refresh() resyncs confirmed (the byTag chip source) but does
            // not re-pull the tag list, so a deleted tag would linger in the filter
            // chips — reloadTags() closes that gap.
            reloadAllStats(monthlyStatsViewModel, reportsViewModel)
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
        monthlyState.primaryRefreshRevision,
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
        onRefresh = { reloadAllStats(monthlyStatsViewModel, reportsViewModel) },
        onOpenBudget = { shellState.openStatsSecondary(StatsSecondaryPage.Budget) },
        onOpenRecurring = { shellState.openStatsSecondary(StatsSecondaryPage.Recurring) },
        onOpenIncomePlans = { shellState.openStatsSecondary(StatsSecondaryPage.IncomePlans) },
        onOpenDebtGoals = { shellState.openStatsSecondary(StatsSecondaryPage.DebtGoals) },
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

/**
 * 统计页全量重拉，由下拉刷新与 dashboard-card 变更 effect 共用（P4 stale-refresh）：先 reloadTags 重拉
 * 标签列表（否则删掉的标签会滞留在筛选 chip），再按当前月 + 标签重同步 monthly / budget / reports。抽成
 * 纯函数消除两处逐字重复，调用方显式传 [monthlyState]（与原内联 lambda 捕获完全一致，无行为变化）。
 */
private fun reloadAllStats(
    monthly: MonthlyStatsViewModel,
    reports: StatsReportsViewModel,
) {
    monthly.reloadTags()
    monthly.refresh()
    val state = monthly.uiState.value
    reports.refresh(state.month, state.selectedTag)
}
