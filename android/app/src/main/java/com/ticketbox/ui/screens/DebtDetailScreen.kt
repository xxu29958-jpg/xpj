package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtActivityUiState
import com.ticketbox.viewmodel.DebtActivityViewModel
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import kotlinx.coroutines.delay

/** 操作成功提示的展示时长，到点自动收起，与 [DebtListScreen] 同一惯例。 */
private const val DebtDetailFlashDismissMillis = 4000L

/**
 * ADR-0049 §3 (slice 8c) 欠款详情 + 记账管理 —— [DebtRoute] 内的子页（与欠款列表互斥渲染，自带
 * [BackHandler]：返回回到列表，再返回才关 overlay，[[project_overlay_screen_needs_own_backhandler]]）。
 * 镜像 [DebtListScreen] 的生活流骨架（[AppScrollableContent] + secondary header + [AppPaperCard] +
 * [AppStatusBanner]）。记还款 / 调整 / 作废三类直接写只对 external/manual 欠款开放（[Debt.isDirectWritable]）；
 * 成员/拆账欠款显示走对方确认流程的提示而非按钮。统一动作面板（[DebtActionSheet]）按 [DebtAction] 渲染
 * 相应字段；还款与调整先保留原提交，确认同步后再读取服务端欠款。
 */
// ADR-0049 §3.2 (slice 8d): the detail screen's side-effects, extracted so the screen composable
// loads the participant task, adopts acknowledged folds, and dismisses temporary feedback.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebtDetailScreen(
    viewModel: DebtDetailViewModel,
    proposalViewModel: MemberRepaymentProposalViewModel,
    historyViewModel: DebtActivityViewModel,
    onBack: () -> Unit,
    splitAgreement: SplitAgreementPanel? = null,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val observedProposalState by proposalViewModel.state.collectAsStateWithLifecycle()
    val proposalState = observedProposalState.takeIf {
        it.task?.binding == state.binding && it.task?.debtPublicId == (state.requestedPublicId ?: state.debt?.publicId)
    } ?: MemberProposalUiState()
    val observedHistoryState by historyViewModel.state.collectAsStateWithLifecycle()
    val historyState = boundDebtHistory(state, observedHistoryState)
    val debt = state.debt

    DebtDetailEffects(
        state = state,
        proposalState = proposalState,
        viewModel = viewModel,
        proposalViewModel = proposalViewModel,
        historyViewModel = historyViewModel,
    )

    val callbacks = DebtDetailScreenCallbacks(
        onBack = onBack,
        onRefresh = {
            viewModel.refresh()
            if (debt?.isMember == true) proposalViewModel.refresh()
            historyViewModel.refresh()
            splitAgreement?.model?.refresh()
        },
        onSelectKind = viewModel::selectKind,
        onOpenAction = viewModel::openAction,
        onRecoverDebtWrite = viewModel::recoverDebtWrite,
    )
    DebtDetailContent(
        state = state,
        panels = DebtDetailPanels(
            proposalState = proposalState,
            proposalViewModel = proposalViewModel,
            splitAgreement = splitAgreement?.let { panel ->
                { SplitAgreementDetailPanel(state, proposalState, panel) { viewModel.refresh(); historyViewModel.refresh() } }
            },
            historyState = historyState,
            historyCallbacks = DebtActivityCallbacks(
                onVoidRepayment = { viewModel.openAction(DebtAction.RepaymentVoid, it) },
                onLoadPage = historyViewModel::loadPage,
                onRetry = historyViewModel::refresh,
                onOpenRepayment = historyViewModel::openRepayment,
            ),
        ),
        callbacks = callbacks,
    )
    if (state.activeAction != null) {
        DebtActionSheet(
            state = state,
            viewModel = viewModel,
            onClose = { viewModel.dismissAction() },
        )
    }
    DebtMemberProposalForm(state, proposalState, proposalViewModel)
}
@Composable
internal fun DebtDetailEffects(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    viewModel: DebtDetailViewModel,
    proposalViewModel: MemberRepaymentProposalViewModel,
    historyViewModel: DebtActivityViewModel,
) {
    val debt = state.debt
    LaunchedEffect(proposalViewModel, state.binding, state.requestedPublicId, debt?.isMember) {
        val publicId = state.requestedPublicId ?: debt?.publicId
        if (publicId != null) state.binding?.let { binding ->
            proposalViewModel.load(DebtTask(binding, publicId), readProposals = debt?.isMember == true, debt = debt)
        }
    }
    // 此 effect 仅在进入页面或 key 变化时运行；重入也读取不改变父版本的远端申报变化。
    LaunchedEffect(historyViewModel, state.binding, debt?.publicId, debt?.rowVersion, proposalState.acknowledgedCommandRevision) {
        val task = state.binding?.let { binding -> debt?.let { DebtTask(binding, it.publicId) } }
        historyViewModel.loadDebt(
            task, debt?.rowVersion ?: 0, proposalState.acknowledgedCommandRevision, forceRefresh = true,
        )
    }
    LaunchedEffect(viewModel, proposalState.task, proposalState.committedDebt) {
        val task = proposalState.task ?: return@LaunchedEffect
        proposalState.committedDebt?.let { viewModel.applyMemberResult(task, it) }
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
            DebtActionButtons(
                onAction = onAction,
                // R10⑤：record 币种未知（支持集外）只禁金额动作（还款/调整需币种解析），
                // Void 不带金额（仅 rowVersion+reason）必须保活——否则用户失去作废错账的安全出口。
                amountActionsEnabled = CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode) != null,
            )
        }
    }
}

@Composable
private fun DebtActionButtons(onAction: (DebtAction) -> Unit, amountActionsEnabled: Boolean) {
    AppAdaptiveEditActionLayout(actionCount = if (amountActionsEnabled) 2 else 1,
        compact = false, stackTwoActionsOnNarrow = true) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> DebtActionButtonsStacked(
                onAction = onAction,
                amountActionsEnabled = amountActionsEnabled,
            )
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
            ) {
                if (amountActionsEnabled) {
                    AppSecondaryButton(
                        text = stringResource(R.string.debt_action_adjustment_title),
                        onClick = { onAction(DebtAction.Adjustment) },
                    )
                }
                AppOutlinedButton(
                    onClick = { onAction(DebtAction.Void) },
                    options = AppOutlinedButtonOptions(danger = true),
                ) {
                    Text(stringResource(R.string.debt_action_void_title))
                }
            }
        }
    }
}

/** 还款入口归详情底部操作槽；这里仅保留调整和作废。 */
@Composable
private fun DebtActionButtonsStacked(onAction: (DebtAction) -> Unit, amountActionsEnabled: Boolean) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        if (amountActionsEnabled) {
            AppSecondaryButton(
                text = stringResource(R.string.debt_action_adjustment_title),
                modifier = Modifier.fillMaxWidth(),
                onClick = { onAction(DebtAction.Adjustment) },
            )
        }
        AppOutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { onAction(DebtAction.Void) },
            options = AppOutlinedButtonOptions(danger = true),
        ) {
            Text(stringResource(R.string.debt_action_void_title))
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

@Composable
private fun DebtActionSheet(
    state: DebtDetailUiState,
    viewModel: DebtDetailViewModel,
    onClose: () -> Unit,
) {
    val action = state.activeAction ?: return
    // VM 的 dismissAction 在提交中吞掉关闭；sheet 本体也必须否决 Hidden，
    // 否则 Back/下滑把失败草稿藏进不可见 modal（同 income-busy-hidden 反例）。
    AppBusyGuardedSheet(
        isSubmitting = state.isSubmitting,
        onDismiss = onClose,
        skipPartiallyExpanded = true,
    ) {
        AppSheetScaffold(
            title = stringResource(debtActionTitleRes(action)),
            subtitle = debtDetailTitle(state.actionTarget),
            actions = {
                state.writeMessage?.let { message -> AppStatusBanner(message = message, tone = MessageTone.Info) }
                state.validationError?.let { err ->
                    AppStatusBanner(message = err, tone = MessageTone.Danger)
                }
                AppSheetActionRow(
                    primary = AppSheetAction(
                        text = if (state.isSubmitting) {
                            stringResource(R.string.debt_action_submitting)
                        } else {
                            stringResource(debtActionSubmitRes(action))
                        },
                        onClick = viewModel::submit,
                        enabled = state.canSubmitAction,
                    ),
                    secondary = if (action == DebtAction.Repayment) null else AppSheetAction(
                        text = stringResource(R.string.common_cancel),
                        onClick = onClose,
                        enabled = !state.isSubmitting,
                    ),
                )
                if (action == DebtAction.Repayment) TextButton(onClick = onClose, enabled = !state.isSubmitting,
                    modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.debt_proposal_back_keep_draft)) }
            },
        ) {
            DebtActionForm(state, viewModel, action)
        }
    }
}

@Composable
private fun DebtActionForm(
    state: DebtDetailUiState,
    viewModel: DebtDetailViewModel,
    action: DebtAction,
) {
    // 金额输入只属于还款/调整；整笔作废(Void)与单笔还款作废(RepaymentVoid)都不带金额。
    if (action == DebtAction.Adjustment) {
        AppAmountInput(
            state = AppAmountInputState(
                label = stringResource(debtActionAmountLabelRes(action)),
                // 显示与解析同源于 record 币种（state.amountInputCurrency），
                // 不读恒 Base 的环境 display（PR#255 P1）。
                currency = state.amountInputCurrency,
                value = state.amountInput,
                enabled = state.canModify && !state.isSubmitting,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                isError = state.validationError != null,
            ),
            actions = AppAmountInputActions(onValueChange = { viewModel.updateActionInput(amount = it) }),
            modifier = Modifier.fillMaxWidth(),
        )
    }
    if (action == DebtAction.Repayment) {
        DebtPaymentAmountField(state.amountInputCurrency, state.amountInput, state.canModify && !state.isSubmitting,
            state.validationError != null) { viewModel.updateActionInput(amount = it) }
        DebtDateField(state.paymentTime?.date.orEmpty(), state.canModify && !state.isSubmitting) {
            viewModel.updateActionInput(paymentDate = it)
        }
        state.debt?.let { DebtRepaymentBalancePreview(it, state.amountInput) }
        TextButton(onClick = { viewModel.dismissAction(discard = true) }, enabled = !state.isSubmitting) {
            Text(stringResource(R.string.debt_proposal_discard_draft))
        }
    }
    if (action == DebtAction.Adjustment) {
        DebtAdjustmentSignChips(increase = state.adjustmentIncrease, onSelect = { viewModel.updateActionInput(adjustmentIncrease = it) })
    }
    // 单笔还款作废：选中还款的只读摘要确认作废对象，无金额输入。
    if (action == DebtAction.RepaymentVoid) {
        state.repaymentToVoid?.let { repayment ->
            DebtRepaymentVoidTarget(repayment = repayment, homeCurrencyCode = (state.actionTarget ?: state.debt)?.homeCurrencyCode)
        }
    }
    if (action != DebtAction.Repayment) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.debt_action_reason_label),
                value = state.reasonInput,
            ),
            actions = AppTextInputActions(onValueChange = { viewModel.updateActionInput(reason = it) }),
            modifier = Modifier.fillMaxWidth(),
        )
    }
    DebtActionWarning(action)
    DebtActionReadFeedback(state, viewModel::refresh) { viewModel.updateActionInput(reviewLatest = true) }
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
