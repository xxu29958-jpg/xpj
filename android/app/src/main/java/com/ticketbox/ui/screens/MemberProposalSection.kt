package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AlertDialog
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.screens.expense.ExpenseTimeDatePicker
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.ProposalForm

/**
 * ADR-0049 §3.2 (slice 8d) 成员欠款 repayment proposal 收发箱 —— [DebtDetailScreen] 对**成员**欠款渲染的
 * 动作面板（替换 slice8c 留的「走对方确认流程」占位提示）。角色由**服务端权威字段** [Debt.viewerIsDebtor]
 * 给出（客户端不推导——详见 [Debt] 的 KDoc）：债务人发起「我已还款」/ 撤回，
 * 债权人确认（全额/部分）/ 拒绝。已结清/作废/只读各显示对应说明。**在途 pending** 由债务人/债权人卡承载，
 * 已解决 proposal 由完整往来时间线承接；这里仅保留当前申报的处理动作。
 * 这些 composable 独立成文件而非堆进 DebtDetailScreen.kt，避免顶破后者的文件级 TooManyFunctions 门
 * （[[project_android_compose_detekt_limits]]）。复用 DebtDetailScreen 的 internal [DebtNoteCard] /
 * [DebtActionFormButtons] 与 DebtGoalLabels 的 [DebtStatusBadge]。
 */
@Composable
internal fun MemberProposalSection(
    debt: Debt,
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)) {
        when {
            state.originalAttempt != null -> Unit // The detail route renders the focused original-submission task.
            debt.isVoided -> DebtNoteCard(stringResource(R.string.debt_proposal_voided_note))
            debt.isCleared -> DebtNoteCard(stringResource(
                if (debt.sourceType in setOf("bill_split", "bill_split_return")) R.string.split_agreement_leg_cleared
                else R.string.debt_proposal_cleared_note,
            ))
            state.task == null -> Unit
            !state.canModify -> DebtNoteCard(stringResource(R.string.debt_proposal_readonly_note))
            debt.viewerIsDebtor == null -> DebtNoteCard(stringResource(R.string.debt_proposal_not_party_note))
            !state.hasReadableProposalState -> {
                if (!state.isLoading) {
                    TextButton(onClick = viewModel::refresh) { Text(stringResource(R.string.common_retry)) }
                }
            }
            debt.viewerIsDebtor == true -> DebtorProposalCard(state = state, viewModel = viewModel)
            else -> CreditorProposalCard(debt = debt, state = state, viewModel = viewModel)
        }
    }
}

@Composable
private fun DebtorProposalCard(state: MemberProposalUiState, viewModel: MemberRepaymentProposalViewModel) {
    val task = state.task ?: return
    val pending = state.pendingProposal
    AppPaperCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(R.string.debt_proposal_debtor_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            if (pending != null) {
                Text(
                    stringResource(R.string.debt_proposal_debtor_pending_hint),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                AppOutlinedButton(
                    onClick = { viewModel.withdraw(task, pending.publicId) },
                    options = AppOutlinedButtonOptions(enabled = !state.isSubmitting),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(stringResource(R.string.debt_proposal_withdraw_action)) }
            } else {
                // §1.4 post-reject：对方回了「金额对不上」且当前无在途 → neutral 提示 + 复用下方重发入口
                // （描述对方动作 + 邀请重试，不指责债务人，绝不 danger）。
                if (state.showDebtorAfterReject) {
                    Text(
                        stringResource(R.string.debt_proposal_debtor_after_reject),
                        style = MaterialTheme.typography.bodyMedium,
                        color = LocalStateTokens.current.neutral.fg,
                    )
                }
                Text(
                    stringResource(R.string.debt_proposal_debtor_hint),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun CreditorProposalCard(
    debt: Debt,
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
) {
    val task = state.task ?: return
    val pending = state.pendingProposal
    AppPaperCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(R.string.debt_proposal_creditor_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            if (pending == null) {
                Text(
                    stringResource(R.string.debt_proposal_creditor_waiting),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 8e ④ forgive：仅债权人 + open 成员债 + 无在途 proposal（pending==null）时显示，低调
                // TextButton，不与「确认收款」抢主操作（pending 时只给确认/拒绝，避免与债务人在途请求并存）。
                CreditorForgiveAction(task = task, debt = debt, isSubmitting = state.isSubmitting, viewModel = viewModel)
            } else {
                Text(
                    stringResource(
                        R.string.debt_proposal_creditor_pending,
                        // 提出金额按 proposal 自带的服务端 homeCurrencyCode 渲染（record 口径，
                        // 与确认表单的解析同源），不读恒 Base 的环境 display（PR#255 P1）。
                        formatDisplayAmount(
                            pending.proposedAmountCents,
                            CurrencyDisplay.forRecord(pending.homeCurrencyCode),
                        ),
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                )
                pending.note?.takeIf { it.isNotBlank() }?.let { note ->
                    Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                AppOutlinedButton(
                    onClick = { viewModel.reject(task, pending.publicId) },
                    options = AppOutlinedButtonOptions(enabled = !state.isSubmitting),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(stringResource(R.string.debt_proposal_reject_action)) }
            }
        }
    }
}

internal fun memberProposalPrimaryAction(
    debt: Debt,
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
) : (@Composable () -> Unit)? {
    val task = state.task ?: return null
    if (!state.canStartCommand || debt.viewerIsDebtor == null || !state.hasReadableProposalState) return null
    val pending = state.pendingProposal
    val form = state.retainedForm ?: when {
        !debt.isOpen -> return null
        debt.viewerIsDebtor && pending == null -> ProposalForm.Propose
        !debt.viewerIsDebtor && pending != null -> ProposalForm.Confirm
        else -> return null
    }
    return {
        AppPrimaryButton(
            text = stringResource(if (state.retainedForm != null) R.string.debt_proposal_resume_draft
                else if (form == ProposalForm.Propose) R.string.debt_proposal_propose_action
                else R.string.debt_proposal_confirm_action),
            onClick = { viewModel.openForm(task, form, pending, debt) },
            enabled = !state.isSubmitting,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

// 8e ④ forgive 入口 + 二次确认弹窗（communal 应需而免 + haptic.confirm() 配单向赠与的软触感）。债权人确认后
// viewModel.forgive 把欠款折成 cleared(forgiven)，详情屏重拉到 is_forgiven 暖语；OCC 冲突走 neutral 提示。
@Composable
private fun CreditorForgiveAction(
    task: DebtTask,
    debt: Debt,
    isSubmitting: Boolean,
    viewModel: MemberRepaymentProposalViewModel,
) {
    var showConfirm by rememberSaveable(task) { mutableStateOf(false) }
    val haptic = rememberAppHaptics()
    TextButton(
        onClick = { showConfirm = true },
        enabled = !isSubmitting,
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.debt_member_forgive_action)) }
    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text(stringResource(R.string.debt_member_forgive_confirm_title)) },
            text = { Text(stringResource(R.string.debt_member_forgive_confirm_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showConfirm = false
                        haptic.confirm()
                        viewModel.forgive(task, debt.rowVersion)
                    },
                ) { Text(stringResource(R.string.debt_member_forgive_confirm_action)) }
            },
            dismissButton = {
                TextButton(onClick = { showConfirm = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ProposalFormSheet(
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
    // 宿主欠款：OCC 载体取 rowVersion，金额解析取其服务端 homeCurrencyCode。
    // 金额输入标签同源于 record 币种（CurrencyDisplay.forRecord）——显示与解析同口径
    // （PR#255 P1：此前标签读恒 Base 的环境 display，JPY 欠款下显示/解析分裂）。
    debt: Debt,
    onClose: () -> Unit,
) {
    val task = state.task ?: return
    AppBusyGuardedSheet(isSubmitting = state.isSubmitting, onDismiss = onClose, skipPartiallyExpanded = true) {
        ProposalForm(
            state = state,
            debt = debt,
            viewModel = viewModel,
            onSubmit = {
                viewModel.submit(
                    task = task,
                    expectedRowVersion = debt.rowVersion,
                    // 严格解析（R7-2）：未知 record 码传 null，VM fail closed 禁用表单写。
                    currency = CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode),
                )
            },
            onCancel = onClose,
        )
    }
}

@Composable
private fun ProposalForm(
    state: MemberProposalUiState,
    debt: Debt,
    viewModel: MemberRepaymentProposalViewModel,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val form = state.activeForm ?: return
    AppSheetScaffold(
        title = stringResource(proposalFormTitleRes(form)),
        subtitle = debt.counterpartyLabel?.let { label -> stringResource(if (debt.viewerIsDebtor == true)
            R.string.debt_payment_direction_out else R.string.debt_payment_direction_in, label) },
        actions = {
            state.validationError?.let { err ->
                AppStatusBanner(message = err, tone = MessageTone.Danger)
            }
            AppSheetActionRow(
                primary = AppSheetAction(
                    text = stringResource(state.submitLabelRes),
                    onClick = onSubmit,
                    enabled = state.canModify && !state.isSubmitting,
                ),
            )
            TextButton(onClick = onCancel, enabled = !state.isSubmitting, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.debt_proposal_back_keep_draft))
            }
        },
    ) {
        ProposalAmountField(state, CurrencyDisplay.forRecord(state.formCurrencyCode ?: debt.homeCurrencyCode), viewModel)
        PaymentDateField(state.paymentTime?.date.orEmpty(), state.inputsEnabled && form == ProposalForm.Propose) { value ->
            state.task?.let { viewModel.updatePaymentDate(it, value) }
        }
        if (form == ProposalForm.Propose) {
            AppTextInput(
                state = AppTextInputState(
                    label = stringResource(R.string.debt_proposal_note_label),
                    value = state.noteInput,
                    enabled = state.inputsEnabled,
                ),
                actions = AppTextInputActions(onValueChange = { value -> state.task?.let { viewModel.updateNote(it, value) } }),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        DebtRepaymentBalancePreview(debt, state.amountInput)
        Text(stringResource(if (form == ProposalForm.Propose) R.string.debt_payment_waiting_confirmation
            else R.string.debt_payment_confirmation_effect), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        TextButton(onClick = { state.task?.let(viewModel::discardDraft) }, enabled = !state.isSubmitting) {
            Text(stringResource(R.string.debt_proposal_discard_draft))
        }
    }
}

@Composable
private fun ProposalAmountField(state: MemberProposalUiState, currency: CurrencyDisplay, viewModel: MemberRepaymentProposalViewModel) {
    AppPaperCard(containerColor = LocalThemeVisuals.current.brandPrimaryBg) {
        AppAmountInput(
            state = AppAmountInputState(label = stringResource(R.string.debt_payment_this_amount), currency = currency.homeCurrency,
                value = state.amountInput, enabled = state.inputsEnabled,
                placeholder = stringResource(R.string.components_amount_input_placeholder), isError = state.validationError != null),
            actions = AppAmountInputActions(onValueChange = { value -> state.task?.let { viewModel.updateAmount(it, value) } }),
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            decorations = AppTextInputDecorations(amountRole = AppAmountRole.Hero),
        )
    }
}

/** Date input and its native picker share the parent's raw value, with no ledger lookup here. */
@Composable
internal fun PaymentDateField(value: String, enabled: Boolean, onChange: (String) -> Unit) {
    var pickingDate by rememberSaveable { mutableStateOf(false) }
    AppTextInput(
        state = AppTextInputState(label = stringResource(R.string.debt_payment_date_label), value = value, enabled = enabled),
        actions = AppTextInputActions(onValueChange = onChange),
        decorations = AppTextInputDecorations(trailingContent = {
            if (enabled) IconButton(onClick = { pickingDate = true }) {
                Icon(ImageVector.vectorResource(R.drawable.ic_lucide_calendar_check),
                    contentDescription = stringResource(R.string.expense_edit_date_pick_date_button))
            }
        }),
    )
    if (pickingDate) ExpenseTimeDatePicker(value, onChange) { pickingDate = false }
}

@StringRes
private fun proposalFormTitleRes(form: ProposalForm): Int = when (form) {
    ProposalForm.Propose -> R.string.debt_proposal_propose_title
    ProposalForm.Confirm -> R.string.debt_proposal_confirm_title
}
