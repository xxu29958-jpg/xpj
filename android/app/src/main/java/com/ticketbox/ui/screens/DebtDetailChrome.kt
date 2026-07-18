package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentStateCopy
import com.ticketbox.ui.components.AppContentStatePresentation
import com.ticketbox.ui.components.AppContentStateSpec
import com.ticketbox.ui.components.AppContentStateSlot
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel

internal data class DebtDetailScreenCallbacks(
    val onBack: () -> Unit,
    val onRefresh: () -> Unit,
    val onSelectKind: (String) -> Unit,
    val onOpenAction: (DebtAction) -> Unit,
    val onVoidRepayment: (String) -> Unit,
    val onLoadMoreRepayments: () -> Unit,
)

@Composable
internal fun DebtDetailContent(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    proposalViewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
    callbacks: DebtDetailScreenCallbacks,
) {
    val debt = state.debt
    val bodyState = debtDetailBodyState(
        hasDebt = debt != null,
        isLoading = state.isLoading,
        error = state.error,
    )
    val readableProposalState = if (debt?.isMember == true) proposalState else MemberProposalUiState()
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
    ) {
        debtDetailStatusItems(
            state = state,
            proposalState = readableProposalState,
            bodyState = bodyState,
        )
        debtDetailBodyItems(
            state = state,
            proposalState = readableProposalState,
            proposalViewModel = proposalViewModel,
            currency = currency,
            callbacks = callbacks,
        )
    }
}

private fun LazyListScope.debtDetailBodyItems(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    proposalViewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
    callbacks: DebtDetailScreenCallbacks,
) {
    val bodyState = debtDetailBodyState(
        hasDebt = state.debt != null,
        isLoading = state.isLoading,
        error = state.error,
    )
    when (bodyState) {
        DebtDetailBodyState.Loading,
        DebtDetailBodyState.LoadFailed -> item {
            DebtDetailBodyStateSlot(
                bodyState = bodyState,
                error = state.error,
                onRetry = callbacks.onRefresh,
            )
        }
        DebtDetailBodyState.Content -> state.debt?.let { debt ->
            if (debt.isMember) {
                debtDetailMemberItems(debt, proposalState, proposalViewModel, currency)
            } else {
                debtDetailExternalItems(debt, state.canModify, currency, callbacks)
            }
            debtRepaymentHistoryItem(
                debt = debt,
                state = state,
                currency = currency,
                onUndo = callbacks.onVoidRepayment,
                onLoadMore = callbacks.onLoadMoreRepayments,
            )
            if (!debt.isMember) {
                item {
                    DebtActionPanel(
                        debt = debt,
                        canModify = state.canModify,
                        onAction = callbacks.onOpenAction,
                    )
                }
            }
        }
    }
}

@Composable
private fun debtDetailTitle(debt: Debt?): String =
    debt?.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: debt?.let { stringResource(debtCounterpartyFallbackRes(it.counterpartyType)) }
        ?: stringResource(R.string.debt_detail_title)

@Composable
private fun debtDetailSubtitle(debt: Debt?): String? = debt?.let { loaded ->
    val directionRes =
        if (loaded.isMember) memberDebtDirectionRes(loaded.viewerIsDebtor) else debtDirectionLabelRes(loaded.direction)
    stringResource(directionRes)
}

private fun LazyListScope.debtDetailStatusItems(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    bodyState: DebtDetailBodyState,
) {
    state.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
    proposalState.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
    debtDetailInlineMessage(bodyState = bodyState, message = state.error)?.let { err ->
        item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
    }
    proposalState.error?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
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
    currency: CurrencyDisplay,
) {
    item { MemberSharedThingCard(debt = debt, currency = currency) }
    item {
        MemberProposalSection(
            debt = debt,
            state = proposalState,
            viewModel = proposalViewModel,
            currency = currency,
        )
    }
}

private fun LazyListScope.debtDetailExternalItems(
    debt: Debt,
    canModify: Boolean,
    currency: CurrencyDisplay,
    callbacks: DebtDetailScreenCallbacks,
) {
    item { DebtSummaryCard(debt = debt, currency = currency) }
    item {
        DebtKindCardWithEditor(
            debt = debt,
            canModify = canModify,
            onSelect = callbacks.onSelectKind,
        )
    }
    debtInstallmentItem(debt = debt, currency = currency)
}

private fun LazyListScope.debtRepaymentHistoryItem(
    debt: Debt,
    state: DebtDetailUiState,
    currency: CurrencyDisplay,
    onUndo: (String) -> Unit,
    onLoadMore: () -> Unit,
) {
    val historyIsFresh = !state.isRepaymentHistoryLoading && state.repaymentHistoryError == null
    val undoableIds = state.repaymentHistory
        ?.items
        .orEmpty()
        .filter { repayment ->
            canVoidRepayment(
                debt = debt,
                history = state.repaymentHistory,
                repayment = repayment,
                canModify = state.canModify,
                historyIsFresh = historyIsFresh,
            )
        }
        .mapTo(mutableSetOf()) { it.publicId }
    item {
        DebtRepaymentHistoryCard(
            state = DebtRepaymentHistoryCardState(
                history = state.repaymentHistory,
                isLoading = state.isRepaymentHistoryLoading,
                error = state.repaymentHistoryError,
                isLoadingMore = state.isRepaymentHistoryLoadingMore,
                loadMoreError = state.repaymentHistoryLoadMoreError,
                undoablePublicIds = undoableIds,
            ),
            currency = currency,
            onUndo = onUndo,
            onLoadMore = onLoadMore,
        )
    }
}
