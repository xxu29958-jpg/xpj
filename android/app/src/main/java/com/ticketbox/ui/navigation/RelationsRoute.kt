package com.ticketbox.ui.navigation

import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SecondaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePanePurpose
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.appAdaptiveSupportingPaneContent
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.screens.DebtAddSheet
import com.ticketbox.ui.screens.DebtBillParseIconButton
import com.ticketbox.ui.screens.DebtFlashDismissMillis
import com.ticketbox.ui.screens.RelationsListChrome
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel
import com.ticketbox.viewmodel.debtViewModelFactory
import com.ticketbox.viewmodel.updateDraftDirection
import kotlinx.coroutines.delay

/** 域级新建抽屉的 VM key：与两个 tab 的列表 VM 实例隔离（同 ViewModelStore 内按 key 区分）。 */
private const val RelationsDebtComposerViewModelKey = "relations-debt-composer"

internal enum class ObligationsView {
    I_OWE,
    OWED_TO_ME,
}

internal data class ObligationsNavigationActions(
    val onOpenAllDebts: () -> Unit,
    val onOpenBillSplits: () -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDebtGoals: () -> Unit,
)

/**
 * 往来域根（W2-C IA）：两个**个人**透镜 tab（我欠 = payables lens / 欠我 = receivables 合并
 * lens）与列表始终同主 pane；全账本视图退为导航区二级页「全部往来」（带当前账本名）。
 * 双标题退役（shell 已有域名）；单主 CTA「记一笔欠款」由域级 composer 承载、两 tab 共享
 * （欠我 tab 方向预选应收），OCR「识别还款账单」为 quiet 入口；Viewer 只读时整行 CTA 不渲染。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun RelationsRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    var selectedView by rememberSaveable { mutableStateOf(ObligationsView.I_OWE) }
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    val navigationActions = ObligationsNavigationActions(
        onOpenAllDebts = { shellState.openSecondaryPage(ProductSecondaryPage.AllDebts) },
        onOpenBillSplits = { shellState.openSecondaryPage(ProductSecondaryPage.BillSplits) },
        onOpenRepaymentReview = { shellState.openRepaymentDrafts() },
        onOpenDebtGoals = { shellState.openSecondaryPage(ProductSecondaryPage.DebtGoals) },
    )

    // 创建落账后 bump revision，可见 tab 的列表路由据此刷新（镜像 MainShellState 修订号惯例）。
    var listRefreshRevision by rememberSaveable { mutableIntStateOf(0) }
    val composer = RelationsComposerHost(
        screenFactory = screenFactory,
        selectedView = selectedView,
        onCreatedRefresh = { listRefreshRevision += 1 },
    )

    val navigation: @Composable () -> Unit = {
        ObligationsTaskNavigation(
            actions = navigationActions,
            ledgerName = screenFactory.ledgerRepository.currentLedgerName(),
        )
    }
    val chrome = RelationsListChrome(
        title = "",
        subtitle = null,
        backText = "",
        onBack = null,
        // expanded：导航区在右 supporting pane；compact：沉到列表尾（真实内容上半屏）。
        domainNavigation = if (adaptivePolicy.showsSupportingPane) null else navigation,
        embeddedInDomain = true,
        topChrome = {
            ObligationsPrimaryChrome(
                selectedView = selectedView,
                onSelectView = { selectedView = it },
                composer = composer,
            )
        },
    )

    RelationsAdaptivePaneConsumer(
        navigation = navigation,
        primaryPane = {
            RelationsPrimaryPane(
                selectedView = selectedView,
                screenFactory = screenFactory,
                chrome = chrome,
                listRefreshRevision = listRefreshRevision,
            )
        },
    )
}

/** 域级新建抽屉的呈现把手：RelationsRoute 只读这些状态与动作，创建链路细节全在 host 内。 */
internal class RelationsComposerHandles(
    val canModify: Boolean,
    val isParsingBill: Boolean,
    val flashMessage: UiText?,
    /** 创建链路错误（OCR 识别/准备失败、首载失败）：主 chrome 必须可见，不得静默。 */
    val error: UiText?,
    val actions: RelationsComposerActions,
)

/** composer 动作组（镜像 DebtListScreenActions 惯例，独立类型以符合构造参数门）。 */
internal class RelationsComposerActions(
    /** 用户可见重试（R1）：仅重试读（refresh），保留草稿，不碰 command 资格门。 */
    val onRetry: () -> Unit,
    val onAddDebt: () -> Unit,
    val onParseBillImage: () -> Unit,
)

/**
 * 域级新建 owner host：两 tab 共享同一创建抽屉与账单识别。lens=Ledger 只服务创建契约与
 * 币种信封（创建不是透镜查询）；个人列表数据仍由各 tab 自己的 VM 负责。创建成功后经
 * [onCreatedRefresh] bump 列表修订号。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RelationsComposerHost(
    screenFactory: MainScreenFactory,
    selectedView: ObligationsView,
    onCreatedRefresh: () -> Unit,
): RelationsComposerHandles {
    val composerViewModel: DebtListViewModel = viewModel(
        key = RelationsDebtComposerViewModelKey,
        factory = debtViewModelFactory(screenFactory.debtRepository, DebtListLens.Ledger),
    )
    val composerState by composerViewModel.state.collectAsStateWithLifecycle()
    var showAddSheet by rememberSaveable { mutableStateOf(false) }
    val context = LocalContext.current
    val parseScope = rememberCoroutineScope()
    val debtBillPicker = rememberDebtBillImageLauncher(composerViewModel, context, parseScope)
    // 重入信号（R1，同 tab 列表 StatsRoutes.DebtRoute）：每次进入往来域 reload composer——
    // 切账本离开再进入时角色/币种随 reload 重解析（VM 跨 route 存活，旧账本残留不得困住入口）。
    LaunchedEffect(Unit) { composerViewModel.reload() }
    // 同账本币种未决（首载失败 fail-closed）时打开入口即重试读；在途不重复发，健康不打搅。
    val retryCurrencyIfUnresolved = {
        if (!composerState.homeCurrencyResolved && !composerState.isLoading) composerViewModel.refresh()
    }

    RelationsComposerOverlays(
        composerViewModel = composerViewModel,
        composerState = composerState,
        showAddSheet = showAddSheet,
        onSheetVisibility = { showAddSheet = it },
        onCreatedRefresh = onCreatedRefresh,
    )

    return RelationsComposerHandles(
        canModify = composerState.canModify,
        isParsingBill = composerState.isParsingBill,
        flashMessage = composerState.flashMessage,
        error = composerState.error,
        actions = RelationsComposerActions(
            onRetry = { composerViewModel.refresh() },
            onAddDebt = {
                retryCurrencyIfUnresolved()
                composerViewModel.resetDraft()
                // 欠我 tab 方向预选应收（表单 chips 仍可改）；我欠 tab 保持默认我欠。
                if (selectedView == ObligationsView.OWED_TO_ME) {
                    composerViewModel.updateDraftDirection(DebtDirections.OWED_TO_ME)
                }
                showAddSheet = true
            },
            onParseBillImage = {
                retryCurrencyIfUnresolved()
                debtBillPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            },
        ),
    )
}

/**
 * composer 的覆盖层（新建抽屉 + 一次性副作用）：sheetState 只服务抽屉故收进这里；
 * 抽屉可见性仍由 host 持有（onSheetVisibility），成功落账经 onCreatedRefresh 通知列表。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RelationsComposerOverlays(
    composerViewModel: DebtListViewModel,
    composerState: DebtListUiState,
    showAddSheet: Boolean,
    onSheetVisibility: (Boolean) -> Unit,
    onCreatedRefresh: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    RelationsComposerEffects(
        composerViewModel = composerViewModel,
        composerState = composerState,
        onAddSucceeded = {
            onSheetVisibility(false)
            onCreatedRefresh()
            composerViewModel.resetDraft()
        },
        onBillParsePrefill = {
            onSheetVisibility(true)
            composerViewModel.ackBillParsePrefill()
        },
    )

    if (showAddSheet) {
        DebtAddSheet(
            state = composerState,
            viewModel = composerViewModel,
            sheetState = sheetState,
            onClose = { onSheetVisibility(false); composerViewModel.resetDraft() },
        )
    }
}

/** 域级新建抽屉的一次性信号/成功/flash 副作用（镜像 DebtListScreen 的既有惯例）。 */
@Composable
private fun RelationsComposerEffects(
    composerViewModel: DebtListViewModel,
    composerState: DebtListUiState,
    onAddSucceeded: () -> Unit,
    onBillParsePrefill: () -> Unit,
) {
    LaunchedEffect(composerState.addSucceeded) {
        if (composerState.addSucceeded) onAddSucceeded()
    }
    LaunchedEffect(composerState.pendingBillParsePrefill) {
        if (composerState.pendingBillParsePrefill) onBillParsePrefill()
    }
    LaunchedEffect(composerState.flashMessage) {
        if (composerState.flashMessage == null) return@LaunchedEffect
        delay(DebtFlashDismissMillis)
        composerViewModel.dismissFlash()
    }
}

/**
 * Production adaptive assembly for the obligations domain.
 *
 * Kept independently mountable so adaptive tests exercise this real consumer (including its
 * navigation pane) without constructing network-backed route repositories.
 */
@Composable
internal fun RelationsAdaptivePaneConsumer(
    navigation: @Composable () -> Unit,
    primaryPane: @Composable () -> Unit,
) {
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Obligations,
        policy = adaptivePolicy,
        primaryPane = primaryPane,
        supportingPane = appAdaptiveSupportingPaneContent(
            purpose = AppAdaptivePanePurpose.ObligationNavigation,
        ) {
            AppAdaptiveSupportingPane(role = AppPageRole.Ledger) {
                navigation()
            }
        },
    )
}

@Composable
private fun RelationsPrimaryPane(
    selectedView: ObligationsView,
    screenFactory: MainScreenFactory,
    chrome: RelationsListChrome,
    listRefreshRevision: Int,
) {
    when (selectedView) {
        ObligationsView.I_OWE -> DebtRoute(
            screenFactory = screenFactory,
            onBack = {},
            chromeOverride = chrome,
            lens = DebtListLens.Payables,
            listRefreshRevision = listRefreshRevision,
        )

        ObligationsView.OWED_TO_ME -> ReceivablesRoute(
            screenFactory = screenFactory,
            onBack = {},
            chromeOverride = chrome,
            listRefreshRevision = listRefreshRevision,
        )
    }
}

/** 主域首屏 chrome：tabs（任务视角切换）+ 单主 CTA；OCR 为 quiet 入口。作为列表首项随内容滚动。 */
@Composable
internal fun ObligationsPrimaryChrome(
    selectedView: ObligationsView,
    onSelectView: (ObligationsView) -> Unit,
    composer: RelationsComposerHandles,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        ObligationsTabs(selectedView = selectedView, onSelectView = onSelectView)
        if (composer.canModify) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                PrimaryCtaButton(
                    text = stringResource(R.string.debt_list_add),
                    icon = Icons.Default.Add,
                    modifier = Modifier.weight(1f),
                    enabled = !composer.isParsingBill,
                    onClick = composer.actions.onAddDebt,
                )
                DebtBillParseIconButton(
                    isParsingBill = composer.isParsingBill,
                    onClick = composer.actions.onParseBillImage,
                )
            }
        }
        composer.flashMessage?.let { AppStatusBanner(message = it, tone = MessageTone.Success) }
        // 错误可见且可继续（R1）：banner 旁给用户重试，不再只有静默文案。
        composer.error?.let { error ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppStatusBanner(
                    message = error,
                    tone = MessageTone.Danger,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = composer.actions.onRetry, enabled = !composer.isParsingBill) {
                    Text(stringResource(R.string.common_retry))
                }
            }
        }
    }
}

@Composable
private fun ObligationsTabs(
    selectedView: ObligationsView,
    onSelectView: (ObligationsView) -> Unit,
) {
    val views = listOf(
        ObligationsView.I_OWE to stringResource(R.string.relations_i_owe_tab),
        ObligationsView.OWED_TO_ME to stringResource(R.string.relations_owed_to_me_tab),
    )
    SecondaryTabRow(
        selectedTabIndex = views.indexOfFirst { it.first == selectedView },
        containerColor = MaterialTheme.colorScheme.surface,
    ) {
        views.forEach { (view, label) ->
            Tab(
                selected = selectedView == view,
                onClick = { onSelectView(view) },
                text = { Text(label) },
            )
        }
    }
}

/** 导航区：全账本二级视图 + 往来任务。expanded 放右 pane；compact 沉到列表尾。 */
@Composable
internal fun ObligationsTaskNavigation(
    actions: ObligationsNavigationActions,
    ledgerName: String?,
) {
    Column {
        Text(
            text = stringResource(R.string.relations_task_section_title),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.fillMaxWidth(),
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_all_debts),
            supporting = ledgerName,
            onClick = actions.onOpenAllDebts,
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_bill_splits),
            onClick = actions.onOpenBillSplits,
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_repayment_review),
            onClick = actions.onOpenRepaymentReview,
        )
        ObligationsTaskRow(
            title = stringResource(R.string.relations_debt_goals),
            onClick = actions.onOpenDebtGoals,
            showDivider = false,
        )
    }
}

@Composable
private fun ObligationsTaskRow(
    title: String,
    onClick: () -> Unit,
    supporting: String? = null,
    showDivider: Boolean = true,
) {
    AppListRow(
        onClick = onClick,
        showDivider = showDivider,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
            )
            supporting?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
