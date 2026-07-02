package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
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
        debtDetailStatusItems(state = state, proposalState = proposalState)
        debt?.let { loaded ->
            if (loaded.isMember) {
                debtDetailMemberItems(
                    debt = loaded,
                    proposalState = proposalState,
                    proposalViewModel = proposalViewModel,
                    currency = currency,
                )
            } else {
                debtDetailExternalItems(
                    debt = loaded,
                    canModify = state.canModify,
                    currency = currency,
                    callbacks = callbacks,
                )
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
) {
    state.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
    proposalState.flashMessage?.let { msg -> item { AppStatusBanner(message = msg, tone = MessageTone.Success) } }
    state.error?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
    proposalState.error?.let { err -> item { AppStatusBanner(message = err, tone = MessageTone.Danger) } }
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
    item {
        DebtActionPanel(
            debt = debt,
            canModify = canModify,
            onAction = callbacks.onOpenAction,
        )
    }
}
