package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.DebtActivityUiState
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel

internal data class DebtDetailScreenCallbacks(
    val onBack: () -> Unit,
    val onRefresh: () -> Unit,
    val onSelectKind: (String) -> Unit,
    val onOpenAction: (DebtAction) -> Unit,
    val onRecoverDebtWrite: (com.ticketbox.data.repository.PendingDebtWrite, Boolean) -> Unit,
)

/** 历史中的还款作废仍走详情命令；翻页、定位关联还款、重试由只读 activity VM 承接。 */
internal data class DebtActivityCallbacks(
    val onVoidRepayment: (DebtRepayment) -> Unit,
    val onLoadPage: (Int) -> Unit,
    val onRetry: () -> Unit,
    val onOpenRepayment: (String) -> Unit = {},
)

/** 详情屏的成员还款操作区与统一往来历史。 */
internal data class DebtDetailPanels(
    val proposalState: MemberProposalUiState,
    val proposalViewModel: MemberRepaymentProposalViewModel,
    val historyState: DebtActivityUiState,
    val historyCallbacks: DebtActivityCallbacks,
    val splitAgreement: (@Composable () -> Unit)? = null,
)

@Composable
internal fun DebtDetailContent(
    state: DebtDetailUiState,
    panels: DebtDetailPanels,
    callbacks: DebtDetailScreenCallbacks,
) {
    val debt = state.debt
    val bodyState = debtDetailBodyState(
        hasDebt = debt != null,
        isLoading = state.isLoading,
        error = state.error,
    )
    val readableProposalState = if (debt?.isMember == true || debt == null) panels.proposalState else MemberProposalUiState()
    if (readableProposalState.originalAttempt != null) {
        MemberOriginalSubmission(state, readableProposalState, panels.proposalViewModel, callbacks)
        return
    }
    val originalRepayment = state.pendingWrites.filterNot { it.isTerminal }.singleOrNull()?.takeIf { it.repayment != null }
    var originalRepaymentFocused by rememberSaveable(originalRepayment?.row?.id) { mutableStateOf(true) }
    if (originalRepayment != null && originalRepaymentFocused) {
        DebtRepaymentOriginalSubmission(state, originalRepayment, callbacks, onOpenDebt = {
            originalRepaymentFocused = false
            callbacks.onRefresh()
        })
        return
    }
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = debtDetailTitle(debt),
            subtitle = debtDetailSubtitle(debt),
            backText = stringResource(R.string.debt_detail_back),
            onBack = callbacks.onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = debt != null,
            ),
            onRefresh = callbacks.onRefresh,
        ),
        slots = AppSecondaryPageSlots(bottomBar = debtDetailPrimaryAction(state, panels, callbacks)),
    ) {
        debtDetailStatusItems(
            state = state,
            proposalState = readableProposalState,
            bodyState = bodyState,
        )
        if (state.pendingWrites.isNotEmpty()) item {
            DebtPendingWrites(state, originalRepayment, { originalRepaymentFocused = true }, callbacks.onRecoverDebtWrite)
        }
        debtDetailBodyItems(
            state = state,
            bodyState = bodyState,
            panels = panels.copy(proposalState = readableProposalState),
            callbacks = callbacks,
        )
    }
}

private fun debtDetailPrimaryAction(state: DebtDetailUiState, panels: DebtDetailPanels,
    callbacks: DebtDetailScreenCallbacks): (@Composable () -> Unit)? {
    if (state.hasRepaymentDraft) return {
        AppFloatingActionBar {
            AppPrimaryButton(text = stringResource(R.string.debt_proposal_resume_draft),
                onClick = { callbacks.onOpenAction(DebtAction.Repayment) }, modifier = Modifier.fillMaxWidth())
        }
    }
    val debt = state.debt ?: return null
    val action: (@Composable () -> Unit)? = if (debt.isMember) {
        memberProposalPrimaryAction(debt, panels.proposalState, panels.proposalViewModel)
    } else if (debt.isOpen && state.canWriteActions && CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode) != null) {
        { AppPrimaryButton(text = stringResource(R.string.debt_action_repayment_title),
            onClick = { callbacks.onOpenAction(DebtAction.Repayment) }, modifier = Modifier.fillMaxWidth()) }
    } else null
    return action?.let { content -> { AppFloatingActionBar { content() } } }
}

private fun LazyListScope.debtDetailBodyItems(
    state: DebtDetailUiState,
    bodyState: DebtDetailBodyState,
    panels: DebtDetailPanels,
    callbacks: DebtDetailScreenCallbacks,
) {
    when (bodyState) {
        DebtDetailBodyState.Loading,
        DebtDetailBodyState.LoadFailed -> item {
            DebtDetailBodyStateSlot(
                bodyState = bodyState,
                error = state.error,
                onRetry = callbacks.onRefresh,
            )
        }
        DebtDetailBodyState.Content -> state.debt?.let { loaded ->
            panels.splitAgreement?.let { section -> item { section() } }
            item { DebtReadSource(state.fetchedAt, state.fromCache, state.isLoading) }
            if (loaded.isMember) {
                debtDetailMemberItems(
                    debt = loaded,
                    proposalState = panels.proposalState,
                    proposalViewModel = panels.proposalViewModel,
                )
            } else {
                debtDetailExternalItems(
                    debt = loaded,
                    canModify = state.canWriteActions,
                    callbacks = callbacks,
                )
            }
            // 完整历史对 member/external 同源呈现：member 只读历史，external/manual
            // 的 active 还款另有单笔作废入口（repaymentVoidActionAllowed 门内）。
            item {
                DebtActivitySection(
                    debt = loaded,
                    canModify = state.canWriteActions,
                    history = panels.historyState,
                    callbacks = panels.historyCallbacks,
                )
            }
        }
    }
}

@Composable
internal fun debtDetailTitle(debt: Debt?): String {
    if (debt == null) return stringResource(R.string.debt_detail_title)
    val name = debt.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(debt.counterpartyType))
    return stringResource(when (debtViewDirection(debt)) {
        DebtDirections.I_OWE -> R.string.debt_detail_title_i_owe
        DebtDirections.OWED_TO_ME -> R.string.debt_detail_title_owed_to_me
        else -> R.string.debt_detail_title_third_party
    }, name)
}

@Composable
private fun debtDetailSubtitle(debt: Debt?): String? = debt?.let { loaded ->
    stringResource(if (loaded.isMember) R.string.debt_detail_member_currency
        else R.string.debt_detail_external_currency, loaded.homeCurrencyCode)
}

private fun LazyListScope.debtDetailStatusItems(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    bodyState: DebtDetailBodyState,
) {
    state.writeMessage?.let { message -> item { AppStatusBanner(message = message, tone = MessageTone.Info) } }
    state.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
    proposalState.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
    debtDetailInlineMessage(bodyState = bodyState, message = state.error)?.let { err ->
        item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
    }
    proposalState.error?.let { err -> item { AppStatusBanner(message = err, tone = proposalState.errorTone) } }
}

@Composable
private fun DebtDetailBodyStateSlot(
    bodyState: DebtDetailBodyState,
    error: UiText?,
    onRetry: () -> Unit,
) {
    when (bodyState) {
        DebtDetailBodyState.Loading -> AppContentStateSlot(
            state = AppContentStateSpec(
                loading = true,
                hasData = false,
                copy = AppContentStateCopy(
                    loadingTitle = stringResource(R.string.debt_detail_loading_title),
                    loadingBody = stringResource(R.string.debt_detail_loading_body),
                    emptyText = stringResource(R.string.debt_detail_loading_body),
                ),
                presentation = AppContentStatePresentation.Card,
            ),
        )
        DebtDetailBodyState.LoadFailed -> AppErrorState(
            title = error?.asString() ?: stringResource(R.string.debt_detail_load_failed),
            body = stringResource(R.string.debt_detail_load_failed_hint),
            onRetry = onRetry,
        )
        DebtDetailBodyState.Content -> Unit
    }
}

private fun LazyListScope.debtDetailMemberItems(
    debt: Debt,
    proposalState: MemberProposalUiState,
    proposalViewModel: MemberRepaymentProposalViewModel,
) {
    item { DebtSummaryCard(debt = debt) }
    item {
        MemberProposalSection(
            debt = debt,
            state = proposalState,
            viewModel = proposalViewModel,
        )
    }
}

private fun LazyListScope.debtDetailExternalItems(
    debt: Debt,
    canModify: Boolean,
    callbacks: DebtDetailScreenCallbacks,
) {
    item { DebtSummaryCard(debt = debt) }
    item {
        DebtKindCardWithEditor(
            debt = debt,
            canModify = canModify,
            onSelect = callbacks.onSelectKind,
        )
    }
    debtInstallmentItem(debt = debt)
    item {
        DebtActionPanel(
            debt = debt,
            canModify = canModify,
            onAction = callbacks.onOpenAction,
        )
    }
}
