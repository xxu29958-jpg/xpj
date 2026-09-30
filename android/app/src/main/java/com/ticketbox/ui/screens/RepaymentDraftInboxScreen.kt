package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateMessage
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.RepaymentDraftInboxUiState
import com.ticketbox.viewmodel.RepaymentDraftInboxViewModel
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与 [DebtListScreen] 的 flash 同惯例。 */
private const val RepaymentDraftFlashDismissMillis = 4000L

/** 一条还款草稿卡的动作态：空闲可操作 / 本卡正在处理 / 禁用（只读账本或别的卡在处理中）。 */
private enum class DraftRowAction { Idle, Busy, Disabled }

/**
 * ADR-0049 §杠杆③ (slice 3a) NLS 还款捕获复核箱 —— 列 pending 还款草稿，每条「选债确认」（底部抽屉选一笔
 * open 外部手动欠款 → 记还款）或「忽略」。镜像 [DebtListScreen]：列表走 [AppScrollableContent] + in-content
 * 返回，反馈走页头位的 [AppStatusBanner]，overlay 自带 [BackHandler]。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RepaymentDraftInboxScreen(
    viewModel: RepaymentDraftInboxViewModel,
    onBack: () -> Unit,
    onOpenDebt: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var showHistory by rememberSaveable { mutableStateOf(false) }
    val focused = state.drafts.find { it.publicId == state.focusedDraftPublicId }
    LaunchedEffect(focused?.publicId, focused?.status) { if (focused != null) showHistory = !focused.isPending }
    if (state.reviewId != null) {
        RepaymentReviewScreen(state, viewModel, onOpenDebt)
        return
    }

    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(RepaymentDraftFlashDismissMillis)
        viewModel.dismissFlash()
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.repayment_draft_topbar_title),
            subtitle = stringResource(R.string.repayment_draft_intro_body),
            backText = stringResource(R.string.repayment_draft_topbar_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = state.drafts.isNotEmpty(),
            ),
            onRefresh = viewModel::refresh,
        ),
    ) {
        item {
            RepaymentDraftReadHeader(state, showHistory) { showHistory = it }
        }
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
        }
        readableListInlineError(hasRows = state.drafts.isNotEmpty(), error = state.error)?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        repaymentDraftListSection(
            state = state.copy(drafts = state.drafts.filter { it.isPending != showHistory }),
            showHistory = showHistory,
            actions = RepaymentDraftListActions(
                onOpenDebt = onOpenDebt,
                onOpenPicker = { draft -> viewModel.reviewEditor.openReview(draft.publicId) },
                onDismiss = { id -> viewModel.reviewEditor.openReview(id); viewModel.dismiss(id) },
            ),
        )
    }

}

private data class RepaymentDraftListActions(
    val onOpenDebt: (String) -> Unit,
    val onOpenPicker: (RepaymentDraft) -> Unit,
    val onDismiss: (String) -> Unit,
)

private fun LazyListScope.repaymentDraftListSection(
    state: RepaymentDraftInboxUiState,
    showHistory: Boolean,
    actions: RepaymentDraftListActions,
) {
    val bodyState = readableListBodyState(
        hasRows = state.drafts.isNotEmpty(),
        isLoading = state.isLoading,
        error = state.error,
    )
    if (bodyState != ReadableListBodyState.Content) {
        item {
            RepaymentDraftListStateCard(
                loading = bodyState == ReadableListBodyState.Loading,
                error = state.error.takeIf { bodyState == ReadableListBodyState.LoadFailed },
                showHistory = showHistory,
            )
        }
        return
    }
    items(state.drafts, key = { it.publicId }) { draft ->
        val suggested = state.suggestedDebtByDraftId[draft.publicId]
        RepaymentDraftCard(
            draft = draft,
            suggestedDebt = suggested,
            action = draftRowAction(state, draft.publicId),
            callbacks = RepaymentDraftCardCallbacks(
                onOpenPicker = { actions.onOpenPicker(draft) },
                onDismiss = { actions.onDismiss(draft.publicId) },
                onOpenDebt = { draft.committedDebtPublicId?.let(actions.onOpenDebt) },
            ),
        )
    }
}

/** Per-card action callbacks bundled so [RepaymentDraftCard] stays within the parameter budget. */
private class RepaymentDraftCardCallbacks(
    val onOpenPicker: () -> Unit,
    val onDismiss: () -> Unit,
    val onOpenDebt: () -> Unit,
)

private fun draftRowAction(state: RepaymentDraftInboxUiState, draftPublicId: String): DraftRowAction = when {
    state.pendingActionDraftId == draftPublicId -> DraftRowAction.Busy
    !state.canModify || state.isLoading || state.pendingActionDraftId != null -> DraftRowAction.Disabled
    else -> DraftRowAction.Idle
}

@Composable
private fun RepaymentDraftCard(
    draft: RepaymentDraft,
    suggestedDebt: Debt?,
    action: DraftRowAction,
    callbacks: RepaymentDraftCardCallbacks,
) {
    AppPaperCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Text(stringResource(R.string.repayment_draft_original_money), style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAdaptiveEditAmountRow(
                amount = formatDisplayAmount(draft.originalAmountMinor, CurrencyDisplay.forRecord(draft.originalCurrencyCode)),
                style = AppAdaptiveAmountRowStyle(role = AppAmountRole.Medium),
            ) {
                Column(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        stringResource(repaymentDraftSourceLabelRes(draft.source)),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    draft.merchantLabel?.takeIf { it.isNotBlank() }?.let { label ->
                        Spacer(Modifier.size(AppSpacing.miniGap))
                        Text(
                            label,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.size(AppSpacing.miniGap))
                    Text(
                        stringResource(R.string.repayment_draft_captured_at, draft.capturedAt.take(10)),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (suggestedDebt != null) {
                Spacer(Modifier.size(AppSpacing.compactGap))
                Text(
                    stringResource(R.string.repayment_draft_suggested_target, debtPickerLabel(suggestedDebt)),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            Spacer(Modifier.size(AppSpacing.compactGap))
            HorizontalDivider()
            Spacer(Modifier.size(AppSpacing.compactGap))
            if (draft.isPending) RepaymentDraftCardActions(
                action = action,
                callbacks = callbacks,
            ) else {
                RepaymentDraftResolved(draft, callbacks.onOpenDebt)
                TextButton(onClick = callbacks.onOpenPicker) { Text(stringResource(R.string.repayment_review_history)) }
            }
        }
    }
}

@Composable
private fun RepaymentDraftCardActions(action: DraftRowAction, callbacks: RepaymentDraftCardCallbacks) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End)) {
        TextButton(onClick = callbacks.onDismiss, enabled = action == DraftRowAction.Idle) {
            Text(stringResource(R.string.repayment_draft_dismiss))
        }
        Button(onClick = callbacks.onOpenPicker, enabled = action != DraftRowAction.Busy) {
            Text(stringResource(R.string.repayment_review_open))
        }
    }
}

@Composable
private fun RepaymentDraftListStateCard(
    loading: Boolean,
    error: UiText?,
    showHistory: Boolean,
) {
    AppPaperCard(modifier = Modifier.fillMaxWidth()) {
        AppListStateContent(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            state = AppListStateSpec(
                isEmpty = true,
                loading = loading,
                emptyText = stringResource(if (showHistory) R.string.repayment_draft_history_empty_body else R.string.repayment_draft_empty_body),
                emptyTitle = stringResource(if (showHistory) R.string.repayment_draft_history_empty_title else R.string.repayment_draft_empty_title),
                emptyBody = stringResource(if (showHistory) R.string.repayment_draft_history_empty_body else R.string.repayment_draft_empty_body),
            ),
            message = error?.let { AppListStateMessage(text = it, tone = MessageTone.Danger) },
        ) {
        }
    }
}
