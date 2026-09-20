package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.DebtActivityUiState
import com.ticketbox.viewmodel.MemberProposalUiState

data class SplitAgreementPanel(
    val model: com.ticketbox.viewmodel.SplitAgreementViewModel,
    val onOpenDebt: (String) -> Unit,
)

internal fun boundDebtHistory(detail: DebtDetailUiState, history: DebtActivityUiState): DebtActivityUiState =
    history.takeIf { it.binding == detail.binding && it.debtPublicId == detail.debt?.publicId } ?: DebtActivityUiState()

@Composable
internal fun SplitAgreementDetailPanel(
    detail: DebtDetailUiState,
    proposal: MemberProposalUiState,
    panel: SplitAgreementPanel,
    onAccepted: () -> Unit,
) {
    val model = panel.model
    val observed by model.state.collectAsStateWithLifecycle()
    val debt = detail.debt
    val eligible = debt?.sourceType in setOf("bill_split", "bill_split_return")
    val task = if (eligible) detail.binding?.let { DebtTask(it, requireNotNull(debt).publicId) } else null
    LaunchedEffect(task, debt?.rowVersion, proposal.acknowledgedCommandRevision) { model.load(task) }
    LaunchedEffect(observed.task, observed.acknowledgedRevision) {
        if (observed.task == task && observed.acknowledgedRevision > 0) {
            onAccepted()
        }
    }
    if (task != null && observed.task == task) SplitAgreementSection(observed, model, panel.onOpenDebt)
}

internal fun splitRelationSettled(
    debt: com.ticketbox.domain.model.Debt?,
    binding: com.ticketbox.data.repository.LogicalSessionBinding?,
    state: com.ticketbox.viewmodel.SplitAgreementUiState?,
): Boolean {
    if (debt?.sourceType !in setOf("bill_split", "bill_split_return")) return true
    val agreement = state?.agreement ?: return false
    if (state.task != binding?.let { DebtTask(it, requireNotNull(debt).publicId) }) return false
    val currentLeg = listOfNotNull(agreement.originalDebt, agreement.returnDebt).singleOrNull { it.publicId == debt?.publicId }
    return agreement.settlementNetAmountCents == 0L && !state.loading && state.error == null &&
        currentLeg?.rowVersion == debt?.rowVersion
}
