package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.domain.model.canCreateRepaymentDraft
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.expenseTimeLabel
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.components.ExpenseCategoryMark
import com.ticketbox.ui.screens.settings.SettingsDetailRow
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
import com.ticketbox.viewmodel.loadExpenseFactBundle
import com.ticketbox.viewmodel.loadOlderExpenseRevisions
import com.ticketbox.viewmodel.openBillSplitInviteSheet
import com.ticketbox.viewmodel.openCorrectionSheet
import com.ticketbox.viewmodel.toggleTimelineExpanded
import com.ticketbox.viewmodel.recoverCorrection
import com.ticketbox.viewmodel.recoverBillSplitCreation
import com.ticketbox.viewmodel.refreshCorrectionFact
import com.ticketbox.viewmodel.currentCorrectionItems
import com.ticketbox.viewmodel.currentCorrectionSplits

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
    onRepairCorrectionRate: CorrectionRateAction,
    originalContent: (@Composable () -> Unit)? = null,
) {
    key(state.timelineExpanded) {
        AppSecondaryScrollableColumn(
            modifier = Modifier.testTag("expense-fact"),
            chrome = AppSecondaryPageChrome(
                role = AppPageRole.Ledger,
                title = if (state.timelineExpanded) stringResource(R.string.expense_fact_history_heading)
                    else state.expense?.merchant?.takeIf { it.isNotBlank() } ?: stringResource(R.string.expense_fact_title),
                subtitle = state.expense?.let { expense ->
                    if (state.timelineExpanded) stringResource(R.string.expense_fact_history_subtitle,
                        expense.merchant.orEmpty(), factAmountLabels(expense, state.factBundle).original)
                    else "${expenseTimeLabel(expense).asString()} · ${expense.category}"
                },
                backText = stringResource(if (state.timelineExpanded) R.string.expense_fact_title else R.string.expense_edit_primary_back_button),
                onBack = if (state.timelineExpanded) viewModel::toggleTimelineExpanded else onBack,
                hasBottomBar = false,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ),
            slots = AppSecondaryPageSlots(headingPrefix = {
                state.expense?.takeUnless { state.timelineExpanded }?.let {
                    ExpenseCategoryMark(it.category, AppListDensity.Standard)
                }
            }),
        ) {
            AppStatusBanner(message = state.message, tone = state.messageTone)
            FactInputContinuitySection(state, viewModel)
            FactCorrectionSubmissions(state, viewModel, onRepairCorrectionRate)
            if (state.expense == null) FactBillSplitSubmissions(state, viewModel)
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
                    FactContentSections(state = state, viewModel = viewModel, originalContent = originalContent)
                }
            }
        }
    }

    ExpenseFactSheetHosts(state = state, viewModel = viewModel)
}

@Composable
private fun FactCorrectionSubmissions(state: ExpenseFactUiState, viewModel: ExpenseFactViewModel, onRepairRate: CorrectionRateAction) {
    val (delivered, unresolved) = state.corrections.partition { it.delivered && !it.refreshRequired }
    unresolved.forEach { FactCorrectionSubmission(it, state, viewModel, onRepairRate) }
    if (delivered.isEmpty()) return
    var expanded by rememberSaveable(state.correctionAccess?.binding) { mutableStateOf(false) }
    TextButton(onClick = { expanded = !expanded }) {
        Text(stringResource(if (expanded) R.string.correction_submissions_hide_delivered
            else R.string.correction_submissions_show_delivered, delivered.size))
    }
    if (expanded) delivered.forEach { FactCorrectionSubmission(it, state, viewModel, onRepairRate) }
}

@Composable
private fun FactCorrectionSubmission(pending: PendingExpenseCorrection, state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel, onRepairRate: CorrectionRateAction) {
    ExpenseCorrectionSubmissionCard(pending,
        options = CorrectionSubmissionOptions(canModify = !state.readOnly, busy = state.correctionRecoveryBusy,
            refreshPending = state.expenseLoadState != ExpenseDetailDataLoadState.Loaded ||
                state.currentCorrectionItems == null ||
                state.currentCorrectionSplits == null ||
                state.revisionsLoadState != ExpenseDetailDataLoadState.Loaded ||
                state.factBundleLoadState != ExpenseDetailDataLoadState.Loaded),
        actions = CorrectionSubmissionActions(recover = { drop -> viewModel.recoverCorrection(pending.row.id, drop) },
            reviewFact = viewModel::refreshCorrectionFact,
            repairRate = state.correctionAccess?.binding?.let { binding -> { gap -> onRepairRate(binding, gap) } }))
}

/** Keep the original beside the split action; failed source reads still expose recovery. */
@Composable
private fun FactBillSplitSubmissions(state: ExpenseFactUiState, viewModel: ExpenseFactViewModel) {
    state.billSplitSubmissions.forEach { pending ->
        BillSplitSubmissionCard(pending, !state.readOnly, state.billSplitRecoveryBusy,
            recover = { drop -> viewModel.recoverBillSplitCreation(pending.row.id, drop) })
    }
}

/** 已知内容时的正文段（stale 提示 + 各事实段 + 关联动作）。 */
@Composable
private fun FactContentSections(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
    originalContent: (@Composable () -> Unit)?,
) {
    val expense = state.expense ?: return
    if (state.timelineExpanded) {
        FactTimelineSection(state, viewModel::loadExpenseRevisions,
            viewModel::toggleTimelineExpanded, viewModel::loadOlderExpenseRevisions)
        return
    }
    // 已知内容 + 权威刷新失败：低层级 stale 提示，不抢任务焦点。
    if (state.expenseStale) {
        FactStaleBanner(onRetry = viewModel::retryLoadExpense)
    }
    FactSummarySection(
        expense = expense,
        state = state,
        onRetryBundle = viewModel::loadExpenseFactBundle,
    )
    FactReadingEntries(state, viewModel, originalContent)
    FactTimelineSection(
        state = state,
        onRetryLoad = viewModel::loadExpenseRevisions,
        onToggleExpanded = viewModel::toggleTimelineExpanded,
        onLoadOlder = viewModel::loadOlderExpenseRevisions,
    )
    if (state.readOnly) Text(stringResource(R.string.expense_fact_readonly_hint)) else
        AppPrimaryButton(text = stringResource(R.string.expense_fact_correct_cta), onClick = viewModel::openCorrectionSheet,
            enabled = state.canStartCorrection, modifier = Modifier.fillMaxWidth())
    FactBillSplitSubmissions(state, viewModel)
    if (expense.canInitiateBillSplit(state.readOnly)) {
        ExpenseBillSplitInvitePanel(
            state = ExpenseBillSplitInvitePanelState(
                sent = state.billSplitSent,
                loadState = state.billSplitSentLoadState,
                loading = state.billSplitLoading,
                message = state.billSplitMessage,
                messageTone = state.billSplitMessageTone,
                canStartInvite = state.authoritativeRootReady,
                hasPendingSubmission = state.billSplitSubmissions.isNotEmpty(),
            ),
            actions = ExpenseBillSplitInvitePanelActions(
                onStartInvite = viewModel::openBillSplitInviteSheet,
                onCancelInvite = { id -> state.correctionAccess?.binding?.let { viewModel.cancelBillSplitInvitation(it, id) } },
            ),
        )
    }
    if (expense.canCreateRepaymentDraft(state.readOnly)) {
        ExpenseRepaymentDraftPanel(
            creating = state.repaymentDraftCreating,
            canCreate = state.authoritativeRootReady,
            onCreate = viewModel::createRepaymentDraftFromExpense,
        )
    }
}

/** Shared reading entries retain the original query and command owners. */
@Composable
private fun FactReadingEntries(
    state: ExpenseFactUiState,
    viewModel: ExpenseFactViewModel,
    originalContent: (@Composable () -> Unit)?,
) {
    val expense = state.expense ?: return
    FactMediaSection(
        state = state,
        onLoadFullImage = viewModel::loadFullImage,
        onRetryThumbnail = viewModel::retryLoadThumbnail,
        originalContent = originalContent,
    )
    SettingsDetailRow(stringResource(R.string.expense_fact_lines_entry),
        stringResource(R.string.expense_fact_lines_entry_hint), R.drawable.ic_lucide_receipt_text) {
        FactLinesSection(
            state = state,
            onRetryItems = viewModel::loadExpenseItems,
            onRetrySplits = viewModel::loadExpenseSplits,
            onRefreshFact = viewModel::refreshCorrectionFact,
            onAcknowledgeItems = viewModel::acknowledgeItemsMismatch,
        )
    }
    SettingsDetailRow(stringResource(R.string.expense_fact_offsets_title),
        stringResource(R.string.expense_fact_offsets_entry_hint), R.drawable.ic_lucide_rotate_ccw) {
        FactOffsetsSection(state, viewModel)
    }
    SettingsDetailRow(stringResource(R.string.expense_fact_notes_entry),
        expense.tags?.takeIf { it.isNotBlank() } ?: expense.note.orEmpty(), R.drawable.ic_lucide_tag) {
        FactFieldRows(expense)
    }
}
