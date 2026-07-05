package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与 [DebtListScreen] 同一惯例。 */
private const val DebtDetailFlashDismissMillis = 4000L

/**
 * ADR-0049 §3 (slice 8c) 欠款详情 + 记账管理 —— [DebtRoute] 内的子页（与欠款列表互斥渲染，自带
 * [BackHandler]：返回回到列表，再返回才关 overlay，[[project_overlay_screen_needs_own_backhandler]]）。
 * 镜像 [DebtListScreen] 的生活流骨架（[AppScrollableContent] + secondary header + [AppGlassCard] +
 * [AppStatusBanner]）。记还款 / 调整 / 作废三类直接写只对 external/manual 欠款开放（[Debt.isDirectWritable]）；
 * 成员/拆账欠款显示走对方确认流程的提示而非按钮。统一动作面板（[DebtActionSheet]）按 [DebtAction] 渲染
 * 相应字段，写成功后 ViewModel 把折叠后的欠款换入本地态。
 */
// ADR-0049 §3.2 (slice 8d): the detail screen's side-effects, extracted so the screen composable
// stays under the LongMethod gate. Loads the member proposal收发箱 on entry, refreshes the Debt
// summary after a fold-changing confirm, and auto-dismisses both VMs' success flashes.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebtDetailScreen(
    viewModel: DebtDetailViewModel,
    proposalViewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val proposalState by proposalViewModel.state.collectAsStateWithLifecycle()
    val debt = state.debt

    DebtDetailEffects(
        state = state,
        proposalState = proposalState,
        viewModel = viewModel,
        proposalViewModel = proposalViewModel,
    )

    val callbacks = DebtDetailScreenCallbacks(
        onBack = onBack,
        onRefresh = {
            viewModel.refresh()
            if (debt?.isMember == true) proposalViewModel.refresh()
        },
        onSelectKind = viewModel::selectKind,
        onOpenAction = viewModel::openAction,
    )
    DebtDetailContent(
        state = state,
        proposalState = proposalState,
        proposalViewModel = proposalViewModel,
        currency = currency,
        callbacks = callbacks,
    )
    if (state.activeAction != null) {
        DebtActionSheet(
            state = state,
            currency = currency,
            viewModel = viewModel,
            onClose = viewModel::dismissAction,
        )
    }
    if (debt?.isMember == true && proposalState.activeForm != null) {
        ProposalFormSheet(
            state = proposalState,
            currency = currency,
            viewModel = proposalViewModel,
            expectedRowVersion = debt.rowVersion,
            onClose = proposalViewModel::dismissForm,
        )
    }
}
@Composable
private fun DebtDetailEffects(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    viewModel: DebtDetailViewModel,
    proposalViewModel: MemberRepaymentProposalViewModel,
) {
    val debt = state.debt
    LaunchedEffect(debt?.publicId, debt?.isMember) {
        if (debt != null && debt.isMember) proposalViewModel.load(debt.publicId)
    }
    LaunchedEffect(proposalState.foldChangedAt) {
        if (proposalState.foldChangedAt > 0) viewModel.refresh()
    }
    LaunchedEffect(state.flashMessage) {
        if (state.flashMessage == null) return@LaunchedEffect
        delay(DebtDetailFlashDismissMillis)
        viewModel.dismissFlash()
    }
    LaunchedEffect(proposalState.flashMessage) {
        if (proposalState.flashMessage == null) return@LaunchedEffect
        delay(DebtDetailFlashDismissMillis)
        proposalViewModel.dismissFlash()
    }
}

// Member debt routes to MemberSharedThingCard; this businesslike accounting card serves external
// debt (unchanged) and the member foreign-currency defensive fallback (§2.6) — hence internal.
@Composable
internal fun DebtSummaryCard(debt: Debt, currency: CurrencyDisplay) {
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text(
            stringResource(R.string.debt_detail_remaining),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            formatDisplayAmount(debt.remainingAmountCents, currency),
            style = MaterialTheme.typography.headlineMedium.tabularNum(),
            fontWeight = FontWeight.SemiBold,
        )
        HorizontalDivider()
        DebtSummaryRow(
            label = stringResource(R.string.debt_detail_principal),
            value = formatDisplayAmount(debt.principalAmountCents, currency),
        )
        DebtSummaryRow(
            label = stringResource(R.string.debt_detail_paid),
            value = formatDisplayAmount(debt.paidAmountCents, currency),
        )
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(R.string.debt_detail_status),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            DebtStatusBadge(
                text = stringResource(debtLinkStatusLabelRes(debt.status)),
                tone = debtLinkStatusTone(debt.status),
            )
        }
    }
}

// Shared by DebtSummaryCard and MemberSharedThingCard's "看看账" expander — hence internal.
@Composable
internal fun DebtSummaryRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium.tabularNum(),
            fontWeight = FontWeight.Medium,
        )
    }
}

// Only rendered for non-member (external/manual) debts; member debts route to MemberProposalSection
// (§5.2 / slice8d). External debts are always direct-writable (guard_direct_fact_writable: external
// + manual), so there is no member-note branch here.
@Composable
internal fun DebtActionPanel(debt: Debt, canModify: Boolean, onAction: (DebtAction) -> Unit) {
    when {
        !debt.isOpen -> DebtNoteCard(stringResource(R.string.debt_detail_closed_note))
        !canModify -> Unit
        else -> AppSectionGroup(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            showTopDivider = false,
        ) {
            DebtActionButtons(onAction = onAction)
        }
    }
}

@Composable
private fun DebtActionButtons(onAction: (DebtAction) -> Unit) {
    AppAdaptiveEditActionLayout(actionCount = 3, compact = false) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                AppPrimaryButton(
                    text = stringResource(R.string.debt_action_repayment_title),
                    icon = Icons.Filled.Check,
                    modifier = Modifier.fillMaxWidth(),
                    onClick = { onAction(DebtAction.Repayment) },
                )
                QuietOutlinedButton(
                    text = stringResource(R.string.debt_action_adjustment_title),
                    modifier = Modifier.fillMaxWidth(),
                    onClick = { onAction(DebtAction.Adjustment) },
                )
                AppOutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = { onAction(DebtAction.Void) },
                    danger = true,
                ) {
                    Text(stringResource(R.string.debt_action_void_title))
                }
            }
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
            ) {
                AppPrimaryButton(
                    text = stringResource(R.string.debt_action_repayment_title),
                    icon = Icons.Filled.Check,
                    onClick = { onAction(DebtAction.Repayment) },
                )
                QuietOutlinedButton(
                    text = stringResource(R.string.debt_action_adjustment_title),
                    onClick = { onAction(DebtAction.Adjustment) },
                )
                AppOutlinedButton(onClick = { onAction(DebtAction.Void) }, danger = true) {
                    Text(stringResource(R.string.debt_action_void_title))
                }
            }
        }
    }
}

@Composable
internal fun DebtNoteCard(text: String) {
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        showTopDivider = false,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtActionSheet(
    state: DebtDetailUiState,
    currency: CurrencyDisplay,
    viewModel: DebtDetailViewModel,
    onClose: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        DebtActionForm(
            state = state,
            currency = currency,
            viewModel = viewModel,
            onSubmit = viewModel::submit,
            onCancel = onClose,
        )
    }
}

@Composable
private fun DebtActionForm(
    state: DebtDetailUiState,
    currency: CurrencyDisplay,
    viewModel: DebtDetailViewModel,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val action = state.activeAction ?: return
    AppSheetScaffold(title = stringResource(debtActionTitleRes(action))) {
        if (action != DebtAction.Void) {
            AppAmountInput(
                state = AppAmountInputState(
                    label = stringResource(debtActionAmountLabelRes(action)),
                    currency = currency.homeCurrency,
                    value = state.amountInput,
                    placeholder = stringResource(R.string.components_amount_input_placeholder),
                    isError = state.validationError != null,
                ),
                actions = AppAmountInputActions(onValueChange = viewModel::updateAmount),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (action == DebtAction.Adjustment) {
            DebtAdjustmentSignChips(increase = state.adjustmentIncrease, onSelect = viewModel::setAdjustmentSign)
        }
        if (action != DebtAction.Repayment) {
            AppTextInput(
                state = AppTextInputState(
                    label = stringResource(R.string.debt_action_reason_label),
                    value = state.reasonInput,
                ),
                actions = AppTextInputActions(onValueChange = viewModel::updateReason),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (action == DebtAction.Void) {
            Text(
                stringResource(R.string.debt_action_void_warning),
                style = MaterialTheme.typography.bodySmall,
                color = LocalStateTokens.current.warn.fg,
            )
        }
        state.validationError?.let { err ->
            AppStatusBanner(message = err, tone = MessageTone.Danger)
        }
        AppSheetActionRow(
            primary = AppSheetAction(
                text = if (state.isSubmitting) {
                    stringResource(R.string.debt_action_submitting)
                } else {
                    stringResource(R.string.debt_action_submit)
                },
                onClick = onSubmit,
                enabled = !state.isSubmitting,
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                onClick = onCancel,
                enabled = !state.isSubmitting,
            ),
        )
    }
}

@Composable
private fun DebtAdjustmentSignChips(increase: Boolean, onSelect: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppFilterChip(
            selected = increase,
            onClick = { onSelect(true) },
            label = stringResource(R.string.debt_action_adjustment_increase),
        )
        AppFilterChip(
            selected = !increase,
            onClick = { onSelect(false) },
            label = stringResource(R.string.debt_action_adjustment_decrease),
        )
    }
}
