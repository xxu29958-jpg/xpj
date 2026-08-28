package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.canCreateRepaymentDraft
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseBillSplitInvitePanel
import com.ticketbox.ui.screens.expense.ExpenseBillSplitInvitePanelActions
import com.ticketbox.ui.screens.expense.ExpenseBillSplitInvitePanelState
import com.ticketbox.ui.screens.expense.ExpenseRepaymentDraftPanel
import com.ticketbox.ui.asString
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.acknowledgeItemsMismatch
import com.ticketbox.viewmodel.cancelBillSplitInvitation
import com.ticketbox.viewmodel.createRepaymentDraftFromExpense
import com.ticketbox.viewmodel.loadExpenseRevisions
import com.ticketbox.viewmodel.openBillSplitInviteSheet
import com.ticketbox.viewmodel.openCorrectionSheet
import com.ticketbox.viewmodel.toggleTimelineExpanded

/**
 * A1: confirmed 账单事实屏（read-first）。段落顺序 = 用户任务顺序：
 * 这是什么（摘要/金额）→ 凭证 → 明细/拆账 → 变更记录 → 关联动作（拆账/还款）。
 * 更正从「更正这笔账单」进入组合意图 sheet；旧编辑表单不再渲染 confirmed。
 */
@Composable
fun ExpenseFactScreen(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
    onBack: () -> Unit,
) {
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.expense_fact_title),
            subtitle = stringResource(R.string.expense_fact_subtitle_confirmed),
            backText = "",
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ),
    ) {
        when {
            // 首载：骨架占位（成熟产品的加载形态，不是白屏）。
            state.expense == null && state.expenseLoadState != ExpenseDetailDataLoadState.Failed -> {
                FactLoadingSkeleton()
            }
            // 首载失败：明确错误 + 重试，不冒充空态。
            state.expense == null -> {
                FactLoadFailedSection(
                    message = state.expenseLoadMessage?.asString(),
                    onRetry = viewModel::retryLoadExpense,
                )
            }
            else -> {
                FactContentSections(state = state, viewModel = viewModel)
            }
        }
    }

    ExpenseFactSheetHosts(state = state, viewModel = viewModel)
}

/** 已知内容时的正文段（stale 提示 + 各事实段 + 关联动作）。 */
@Composable
private fun FactContentSections(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
) {
                val expense = state.expense ?: return
                // 已知内容 + 权威刷新失败：低层级 stale 提示，不抢任务焦点。
                if (state.expenseStale) {
                    FactStaleBanner(onRetry = viewModel::retryLoadExpense)
                }
                AppStatusBanner(message = state.message, tone = state.messageTone)
                FactSummarySection(
                    expense = expense,
                    state = state,
                    onOpenCorrection = viewModel::openCorrectionSheet,
                )
                FactMediaSection(
                    state = state,
                    onLoadFullImage = viewModel::loadFullImage,
                    onRetryThumbnail = viewModel::retryLoadThumbnail,
                )
                FactLinesSection(
                    state = state,
                    onRetryItems = viewModel::loadExpenseItems,
                    onRetrySplits = viewModel::loadExpenseSplits,
                    onAcknowledgeItems = viewModel::acknowledgeItemsMismatch,
                )
                FactTimelineSection(
                    state = state,
                    onRetryLoad = viewModel::loadExpenseRevisions,
                    onToggleExpanded = viewModel::toggleTimelineExpanded,
                )
                if (expense.canInitiateBillSplit(state.readOnly)) {
                    ExpenseBillSplitInvitePanel(
                        state = ExpenseBillSplitInvitePanelState(
                            sent = state.billSplitSent,
                            loadState = state.billSplitSentLoadState,
                            loading = state.billSplitLoading,
                            message = state.billSplitMessage,
                            messageTone = state.billSplitMessageTone,
                        ),
                        actions = ExpenseBillSplitInvitePanelActions(
                            onStartInvite = viewModel::openBillSplitInviteSheet,
                            onCancelInvite = viewModel::cancelBillSplitInvitation,
                        ),
                    )
                }
                if (expense.canCreateRepaymentDraft(state.readOnly)) {
                    ExpenseRepaymentDraftPanel(
                        creating = state.repaymentDraftCreating,
                        onCreate = viewModel::createRepaymentDraftFromExpense,
                    )
                }
}
