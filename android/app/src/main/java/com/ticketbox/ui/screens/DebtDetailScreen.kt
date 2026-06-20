package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
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
 * 镜像 [DebtListScreen] 的生活流骨架（[AppScrollableContent] + [AppPageHeader] + [AppGlassCard] +
 * [AppStatusBanner]）。记还款 / 调整 / 作废三类直接写只对 external/manual 欠款开放（[Debt.isDirectWritable]）；
 * 成员/拆账欠款显示走对方确认流程的提示而非按钮。统一动作面板（[DebtActionSheet]）按 [DebtAction] 渲染
 * 相应字段，写成功后 ViewModel 把折叠后的欠款换入本地态。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebtDetailScreen(
    viewModel: DebtDetailViewModel,
    proposalViewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsState()
    val proposalState by proposalViewModel.state.collectAsState()
    val debt = state.debt

    DebtDetailEffects(
        state = state,
        proposalState = proposalState,
        viewModel = viewModel,
        proposalViewModel = proposalViewModel,
    )

    BackHandler(onBack = onBack)

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.isLoading,
        onRefresh = {
            viewModel.refresh()
            if (debt?.isMember == true) proposalViewModel.refresh()
        },
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item { DebtDetailHeader(debt = debt, onBack = onBack) }
        state.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
        proposalState.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
        state.error?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
        proposalState.error?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
        debt?.let { loaded ->
            // ② 成员债换轴：关系卡 + proposal 收发箱；外部债走会计卡 + 直接写动作面板（一字不改）。
            if (loaded.isMember) {
                item { MemberSharedThingCard(debt = loaded, currency = currency) }
                item {
                    MemberProposalSection(
                        debt = loaded,
                        state = proposalState,
                        viewModel = proposalViewModel,
                        currency = currency,
                    )
                }
            } else {
                item { DebtSummaryCard(debt = loaded, currency = currency) }
                // 8e-6e 还款类型（仅外部债）：当前分类卡 + open 债的 owner 点「修改」开选择器纠正（自带本地态）。
                item {
                    DebtKindCardWithEditor(debt = loaded, canModify = state.canModify, onSelect = viewModel::selectKind)
                }
                item { DebtActionPanel(debt = loaded, canModify = state.canModify, onAction = viewModel::openAction) }
            }
        }
    }

    if (state.activeAction != null) {
        DebtActionSheet(state = state, viewModel = viewModel, onClose = viewModel::dismissAction)
    }
    if (debt != null && proposalState.activeForm != null) {
        ProposalFormSheet(
            state = proposalState,
            viewModel = proposalViewModel,
            expectedRowVersion = debt.rowVersion,
            onClose = proposalViewModel::dismissForm,
        )
    }
}

// ADR-0049 §3.2 (slice 8d): the detail screen's side-effects, extracted so the screen composable
// stays under the LongMethod gate. Loads the member proposal收发箱 on entry, refreshes the Debt
// summary after a fold-changing confirm, and auto-dismisses both VMs' success flashes.
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

@Composable
private fun DebtDetailHeader(debt: Debt?, onBack: () -> Unit) {
    val title = debt?.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: debt?.let { stringResource(debtCounterpartyFallbackRes(it.counterpartyType)) }
        ?: stringResource(R.string.debt_detail_title)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = onBack) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.debt_detail_back),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(stringResource(R.string.debt_detail_back))
        }
        AppPageHeader(
            title = title,
            // ② 成员债副标题关系化（你帮我垫的 / 我帮你垫的 / 第三人称）；外部债仍走应付/应收。
            subtitle = debt?.let { d ->
                val directionRes =
                    if (d.isMember) memberDebtDirectionRes(d.viewerIsDebtor) else debtDirectionLabelRes(d.direction)
                stringResource(directionRes)
            },
        )
    }
}

// Member debt routes to MemberSharedThingCard; this businesslike accounting card serves external
// debt (unchanged) and the member foreign-currency defensive fallback (§2.6) — hence internal.
@Composable
internal fun DebtSummaryCard(debt: Debt, currency: CurrencyDisplay) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
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
            Spacer(Modifier.size(AppSpacing.compactGap))
            HorizontalDivider()
            Spacer(Modifier.size(AppSpacing.compactGap))
            DebtSummaryRow(
                label = stringResource(R.string.debt_detail_principal),
                value = formatDisplayAmount(debt.principalAmountCents, currency),
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            DebtSummaryRow(
                label = stringResource(R.string.debt_detail_paid),
                value = formatDisplayAmount(debt.paidAmountCents, currency),
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
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
private fun DebtActionPanel(debt: Debt, canModify: Boolean, onAction: (DebtAction) -> Unit) {
    when {
        !debt.isOpen -> DebtNoteCard(stringResource(R.string.debt_detail_closed_note))
        !canModify -> Unit
        else -> Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Button(onClick = { onAction(DebtAction.Repayment) }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.debt_action_repayment_title))
            }
            OutlinedButton(onClick = { onAction(DebtAction.Adjustment) }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.debt_action_adjustment_title))
            }
            OutlinedButton(onClick = { onAction(DebtAction.Void) }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.debt_action_void_title))
            }
        }
    }
}

@Composable
internal fun DebtNoteCard(text: String) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DebtActionSheet(
    state: DebtDetailUiState,
    viewModel: DebtDetailViewModel,
    onClose: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        DebtActionForm(state = state, viewModel = viewModel, onSubmit = viewModel::submit, onCancel = onClose)
    }
}

@Composable
private fun DebtActionForm(
    state: DebtDetailUiState,
    viewModel: DebtDetailViewModel,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val action = state.activeAction ?: return
    Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
        Text(
            stringResource(debtActionTitleRes(action)),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.cardPadding))
        if (action != DebtAction.Void) {
            OutlinedTextField(
                value = state.amountInput,
                onValueChange = viewModel::updateAmount,
                label = { Text(stringResource(debtActionAmountLabelRes(action))) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (action == DebtAction.Adjustment) {
            Spacer(Modifier.size(AppSpacing.smallGap))
            DebtAdjustmentSignChips(increase = state.adjustmentIncrease, onSelect = viewModel::setAdjustmentSign)
        }
        if (action != DebtAction.Repayment) {
            Spacer(Modifier.size(AppSpacing.compactGap))
            OutlinedTextField(
                value = state.reasonInput,
                onValueChange = viewModel::updateReason,
                label = { Text(stringResource(R.string.debt_action_reason_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (action == DebtAction.Void) {
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.debt_action_void_warning),
                style = MaterialTheme.typography.bodySmall,
                color = LocalStateTokens.current.warn.fg,
            )
        }
        state.validationError?.let { err ->
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(err.asString(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.size(AppSpacing.cardPadding))
        HorizontalDivider()
        Spacer(Modifier.size(AppSpacing.compactGap))
        DebtActionFormButtons(isSubmitting = state.isSubmitting, onSubmit = onSubmit, onCancel = onCancel)
        Spacer(Modifier.size(AppSpacing.compactGap))
    }
}

@Composable
private fun DebtAdjustmentSignChips(increase: Boolean, onSelect: (Boolean) -> Unit) {
    Row(modifier = Modifier.fillMaxWidth()) {
        FilterChip(
            selected = increase,
            onClick = { onSelect(true) },
            label = { Text(stringResource(R.string.debt_action_adjustment_increase)) },
            modifier = Modifier.padding(end = AppSpacing.smallGap),
        )
        FilterChip(
            selected = !increase,
            onClick = { onSelect(false) },
            label = { Text(stringResource(R.string.debt_action_adjustment_decrease)) },
        )
    }
}

@Composable
internal fun DebtActionFormButtons(isSubmitting: Boolean, onSubmit: () -> Unit, onCancel: () -> Unit) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        TextButton(onClick = onCancel) { Text(stringResource(R.string.common_cancel)) }
        Spacer(Modifier.width(AppSpacing.smallGap))
        Button(onClick = onSubmit, enabled = !isSubmitting) {
            Text(
                if (isSubmitting) {
                    stringResource(R.string.debt_action_submitting)
                } else {
                    stringResource(R.string.debt_action_submit)
                },
            )
        }
    }
}
