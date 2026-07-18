package com.ticketbox.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.navigation.ObligationsNavigationActions
import com.ticketbox.ui.navigation.ObligationsView
import com.ticketbox.ui.navigation.RelationsAdaptivePaneConsumer
import com.ticketbox.ui.screens.LedgerScreen
import com.ticketbox.ui.screens.LedgerScreenActions
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.screens.StatsFilterActions
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.ui.screens.StatsScreenActions
import com.ticketbox.ui.screens.pending.PendingDuplicateReviewActions
import com.ticketbox.ui.screens.pending.PendingExpenseQueueActions
import com.ticketbox.ui.screens.pending.PendingQuickFixEntryActions
import com.ticketbox.ui.screens.pending.PendingQueueReviewActions
import com.ticketbox.ui.screens.pending.PendingReviewFlowActions
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.screens.pending.PendingScreenChromeActions
import com.ticketbox.ui.screens.plan.PlanBudgetNavigationActions
import com.ticketbox.ui.screens.plan.PlanScreen
import com.ticketbox.ui.screens.plan.PlanScreenActions
import com.ticketbox.ui.screens.plan.PlanScreenData
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.PendingListLoadState
import com.ticketbox.viewmodel.PendingUiState
import com.ticketbox.viewmodel.RecurringUiState
import com.ticketbox.viewmodel.StatsUiState

/**
 * Mounts the real production consumer for every primary product domain.
 *
 * The exhaustive branch is intentional: removing any Inbox/Pending, Transactions/Ledger,
 * Obligations/Relations, Plans or Insights/Stats consumer makes this instrumentation source stop
 * compiling (or its adaptive pane tags disappear at runtime).
 */
@Composable
internal fun AppAdaptiveRealProductConsumer(domain: AppAdaptiveProductDomain) {
    when (domain) {
        AppAdaptiveProductDomain.Inbox -> PendingScreen(
            state = PendingUiState(
                listLoadState = PendingListLoadState.Loaded,
                hasLoadedOnce = true,
            ),
            chromeActions = pendingChromeActions,
            itemActions = pendingQueueActions,
            reviewActions = pendingReviewActions,
            sheetActions = pendingSheetActions,
        )

        AppAdaptiveProductDomain.Transactions -> LedgerScreen(
            state = LedgerUiState(),
            actions = LedgerScreenActions(),
        )

        AppAdaptiveProductDomain.Obligations -> RelationsAdaptivePaneConsumer(
            selectedView = ObligationsView.I_OWE,
            onSelectView = {},
            actions = obligationsNavigationActions,
            primaryPane = {
                AppPageScrollableColumn(
                    chrome = AppScrollablePageChrome(
                        page = AppPageChrome(
                            role = AppPageRole.Ledger,
                            hasBottomBar = false,
                        ),
                    ),
                ) {
                    AppPageHeader(
                        title = stringResource(R.string.relations_title),
                        subtitle = stringResource(R.string.relations_i_owe_subtitle),
                    )
                }
            },
        )

        AppAdaptiveProductDomain.Plans -> PlanScreen(
            data = PlanScreenData(
                budget = BudgetUiState(),
                recurring = RecurringUiState(),
                income = IncomePlanUiState(),
            ),
            actions = planScreenActions,
        )

        AppAdaptiveProductDomain.Insights -> StatsScreen(
            state = StatsUiState(),
            actions = statsScreenActions,
        )
    }
}

private val pendingChromeActions = PendingScreenChromeActions(
    onRefresh = {},
    onUploadScreenshot = {},
    onOpenProcessing = {},
    onOpenRepaymentReview = {},
    onOpenDataQuality = {},
)

private val pendingQueueActions = PendingExpenseQueueActions(
    onEdit = {},
    onConfirm = {},
    onReject = {},
    onKeepDuplicate = {},
)

private val pendingReviewActions = PendingReviewFlowActions(
    quickFix = PendingQuickFixEntryActions(
        onQuickCategory = {},
        onQuickMerchant = {},
        onMissingAmount = {},
    ),
    duplicate = PendingDuplicateReviewActions(onOpenDuplicate = {}),
    queue = PendingQueueReviewActions(
        onOpenBulkConfirm = {},
        onUndoReject = {},
    ),
)

private val pendingSheetActions = PendingReviewSheetHostActions(
    onSaveQuickCategory = { _, _ -> },
    onSaveQuickMerchant = { _, _ -> },
    onSaveAmountDraft = { _, _ -> },
    onSaveAmountAndConfirm = { _, _ -> },
    onSkipReviewField = {},
    onKeepBoth = {},
    onIgnoreCurrent = {},
    onConfirmReady = {},
    onDismiss = {},
)

private val obligationsNavigationActions = ObligationsNavigationActions(
    onOpenBillSplits = {},
    onOpenRepaymentReview = {},
    onOpenDebtGoals = {},
)

private val planScreenActions = PlanScreenActions(
    budgetNavigation = PlanBudgetNavigationActions(
        onOpenBudget = {},
        onOpenAdvice = {},
    ),
    onOpenSpendingGoal = {},
    onOpenRecurring = {},
    onOpenIncomePlans = {},
    onRefresh = {},
)

private val statsScreenActions = StatsScreenActions(
    filters = StatsFilterActions(
        onMonthChange = {},
        onTagChange = {},
    ),
    onRefresh = {},
    onOpenDataQuality = {},
    reports = StatsReportActions(
        onDrillToLedger = {},
        onGranularityChange = {},
        onRankingMetricChange = {},
    ),
)
