package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
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
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var pickerDraftId by rememberSaveable { mutableStateOf<String?>(null) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(RepaymentDraftFlashDismissMillis)
        viewModel.dismissFlash()
    }

    BackHandler(onBack = onBack)

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.isLoading,
        onRefresh = viewModel::refresh,
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item { RepaymentDraftInboxHeader(onBack = onBack) }
        state.flashMessage?.let { msg ->
            item { AppStatusBanner(message = msg, tone = MessageTone.Success) }
        }
        state.error?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        repaymentDraftListSection(
            state = state,
            currency = currency,
            onConfirmSuggested = { draft, debt -> viewModel.confirm(draft.publicId, debt) },
            onOpenPicker = { draft -> pickerDraftId = draft.publicId },
            onDismiss = viewModel::dismiss,
        )
    }

    val activeDraftId = pickerDraftId
    if (activeDraftId != null) {
        DebtPickerSheet(
            model = DebtPickerModel(
                debts = state.targetDebts,
                suggestedPublicId = state.suggestedDebtByDraftId[activeDraftId]?.publicId,
            ),
            currency = currency,
            sheetState = sheetState,
            onPick = { debt ->
                viewModel.confirm(activeDraftId, debt)
                pickerDraftId = null
            },
            onClose = { pickerDraftId = null },
        )
    }
}

@Composable
private fun RepaymentDraftInboxHeader(onBack: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = onBack) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.repayment_draft_topbar_back),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(stringResource(R.string.repayment_draft_topbar_back))
        }
        AppPageHeader(
            title = stringResource(R.string.repayment_draft_topbar_title),
            subtitle = stringResource(R.string.repayment_draft_intro_body),
        )
    }
}

private fun LazyListScope.repaymentDraftListSection(
    state: RepaymentDraftInboxUiState,
    currency: CurrencyDisplay,
    onConfirmSuggested: (RepaymentDraft, Debt) -> Unit,
    onOpenPicker: (RepaymentDraft) -> Unit,
    onDismiss: (String) -> Unit,
) {
    if (state.drafts.isEmpty() && !state.isLoading) {
        item { RepaymentDraftEmptyStateCard() }
    } else {
        items(state.drafts, key = { it.publicId }) { draft ->
            val suggested = state.suggestedDebtByDraftId[draft.publicId]
            RepaymentDraftCard(
                draft = draft,
                currency = currency,
                suggestedDebt = suggested,
                action = draftRowAction(state, draft.publicId),
                callbacks = RepaymentDraftCardCallbacks(
                    // With a suggestion the primary action confirms it directly; without one it
                    // opens the picker (slice-3a behavior). "选其他欠款" always opens the picker.
                    onConfirmSuggested = { if (suggested != null) onConfirmSuggested(draft, suggested) },
                    onOpenPicker = { onOpenPicker(draft) },
                    onDismiss = { onDismiss(draft.publicId) },
                ),
            )
        }
    }
}

/** Per-card action callbacks bundled so [RepaymentDraftCard] stays within the parameter budget. */
private class RepaymentDraftCardCallbacks(
    val onConfirmSuggested: () -> Unit,
    val onOpenPicker: () -> Unit,
    val onDismiss: () -> Unit,
)

private fun draftRowAction(state: RepaymentDraftInboxUiState, draftPublicId: String): DraftRowAction = when {
    state.pendingActionDraftId == draftPublicId -> DraftRowAction.Busy
    !state.canModify || state.pendingActionDraftId != null -> DraftRowAction.Disabled
    else -> DraftRowAction.Idle
}

@Composable
private fun RepaymentDraftCard(
    draft: RepaymentDraft,
    currency: CurrencyDisplay,
    suggestedDebt: Debt?,
    action: DraftRowAction,
    callbacks: RepaymentDraftCardCallbacks,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
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
                Spacer(Modifier.width(AppSpacing.smallGap))
                Text(
                    formatDisplayAmount(draft.amountCents, currency),
                    style = MaterialTheme.typography.titleLarge.tabularNum(),
                    fontWeight = FontWeight.SemiBold,
                )
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
            RepaymentDraftCardActions(
                action = action,
                hasSuggestion = suggestedDebt != null,
                callbacks = callbacks,
            )
        }
    }
}

@Composable
private fun RepaymentDraftCardActions(
    action: DraftRowAction,
    hasSuggestion: Boolean,
    callbacks: RepaymentDraftCardCallbacks,
) {
    val enabled = action == DraftRowAction.Idle
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        TextButton(onClick = callbacks.onDismiss, enabled = enabled) {
            Text(stringResource(R.string.repayment_draft_dismiss))
        }
        Spacer(Modifier.width(AppSpacing.smallGap))
        if (hasSuggestion) {
            // The server pre-selected a Debt: confirm it directly, or "选其他欠款" to override.
            TextButton(onClick = callbacks.onOpenPicker, enabled = enabled) {
                Text(stringResource(R.string.repayment_draft_choose_other))
            }
            Spacer(Modifier.width(AppSpacing.smallGap))
            Button(onClick = callbacks.onConfirmSuggested, enabled = enabled) {
                Text(repaymentDraftPrimaryLabel(action, R.string.repayment_draft_confirm_suggested))
            }
        } else {
            // No suggestion (slice-3a): the primary action opens the picker to choose a Debt.
            Button(onClick = callbacks.onOpenPicker, enabled = enabled) {
                Text(repaymentDraftPrimaryLabel(action, R.string.repayment_draft_confirm))
            }
        }
    }
}

/** Primary-button label: the busy spinner copy while this draft is processing, else [idleRes]. */
@Composable
private fun repaymentDraftPrimaryLabel(action: DraftRowAction, idleRes: Int): String =
    if (action == DraftRowAction.Busy) {
        stringResource(R.string.repayment_draft_action_busy)
    } else {
        stringResource(idleRes)
    }

@Composable
private fun RepaymentDraftEmptyStateCard() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                stringResource(R.string.repayment_draft_empty_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.repayment_draft_empty_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** The picker's data: the repayable Debt list + which one (if any) the server suggested. */
private class DebtPickerModel(
    val debts: List<Debt>,
    val suggestedPublicId: String?,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtPickerSheet(
    model: DebtPickerModel,
    currency: CurrencyDisplay,
    sheetState: androidx.compose.material3.SheetState,
    onPick: (Debt) -> Unit,
    onClose: () -> Unit,
) {
    // Pin the suggested Debt to the top (stable sort keeps the rest in order); it also gets a badge.
    val ordered = remember(model.debts, model.suggestedPublicId) {
        model.debts.sortedByDescending { it.publicId == model.suggestedPublicId }
    }
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
            Text(
                stringResource(R.string.repayment_draft_picker_title),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            if (ordered.isEmpty()) {
                Text(
                    stringResource(R.string.repayment_draft_picker_empty),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                ordered.forEach { debt ->
                    DebtPickerRow(
                        debt = debt,
                        currency = currency,
                        isSuggested = debt.publicId == model.suggestedPublicId,
                        onPick = { onPick(debt) },
                    )
                }
            }
            Spacer(Modifier.size(AppSpacing.compactGap))
        }
    }
}

@Composable
private fun DebtPickerRow(
    debt: Debt,
    currency: CurrencyDisplay,
    isSuggested: Boolean,
    onPick: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onPick).padding(vertical = AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(debtPickerLabel(debt), style = MaterialTheme.typography.bodyLarge)
        if (isSuggested) {
            Spacer(Modifier.width(AppSpacing.smallGap))
            Text(
                stringResource(R.string.repayment_draft_picker_suggested_badge),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.weight(1f))
        Text(
            stringResource(
                R.string.repayment_draft_picker_remaining,
                formatDisplayAmount(debt.remainingAmountCents, currency),
            ),
            style = MaterialTheme.typography.bodyMedium.tabularNum(),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Display label for a target Debt: its counterparty label, or the type fallback when unlabeled. */
@Composable
private fun debtPickerLabel(debt: Debt): String =
    debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
