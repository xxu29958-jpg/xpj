package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitLedgerActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Account inbox and current-ledger sent history consume canonical invitation results. */
data class BillSplitTargetLedger(val ledgerId: String, val name: String)

enum class BillSplitListLoadState { Unknown, Loading, Loaded, Failed }

data class BillSplitUiState(
    val inbox: List<BillSplitInbox> = emptyList(),
    val sent: List<BillSplitSent> = emptyList(),
    val candidateTargetLedgers: List<BillSplitTargetLedger> = emptyList(),
    val inboxLoadState: BillSplitListLoadState = BillSplitListLoadState.Unknown,
    val sentLoadState: BillSplitListLoadState = BillSplitListLoadState.Unknown,
    val loading: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val access: LedgerAccessContext? = null,
)

class BillSplitViewModel(
    private val billSplitActions: BillSplitActions,
    private val ledgerActions: BillSplitLedgerActions,
) : ViewModel() {
    constructor(expenseRepository: ExpenseRepository, ledgerRepository: LedgerRepository) : this(
        expenseBillSplitActions(expenseRepository), ledgerBillSplitActions(ledgerRepository),
    )

    private val _uiState = MutableStateFlow(initialSplitState(billSplitActions, ledgerActions))
    val uiState: StateFlow<BillSplitUiState> = _uiState.asStateFlow()
    private var operation: Job? = null

    init {
        viewModelScope.launch { billSplitActions.observeAccess().collect { refreshAccess() } }
    }

    private fun refreshAccess(): LedgerAccessContext? {
        val access = billSplitActions.currentAccess()
        if (_uiState.value.access?.binding != access?.binding) {
            operation?.cancel()
            _uiState.value = BillSplitUiState(access = access)
        } else _uiState.update { it.copy(access = access) }
        return access
    }

    private fun updateFor(binding: LogicalSessionBinding, change: (BillSplitUiState) -> BillSplitUiState) {
        if (refreshAccess()?.binding == binding) _uiState.update(change)
    }

    private fun launchBound(expectedBinding: LogicalSessionBinding? = null, block: suspend (LogicalSessionBinding) -> Unit) {
        val binding = refreshAccess()?.binding ?: return
        if (expectedBinding != null && binding != expectedBinding) return
        if (_uiState.value.loading) return
        _uiState.update { it.copy(loading = true, message = null, messageTone = MessageTone.Neutral) }
        operation = viewModelScope.launch {
            if (refreshAccess()?.binding == binding) block(binding)
        }
    }

    fun refresh() = launchBound { load(it) }

    private suspend fun load(binding: LogicalSessionBinding, acknowledged: UiText? = null) {
        updateFor(binding) { it.copy(inboxLoadState = BillSplitListLoadState.Loading, sentLoadState = BillSplitListLoadState.Loading) }
        val ledgers = ledgerActions.refreshLedgers()
        if (refreshAccess()?.binding != binding) return
        val inbox = billSplitActions.fetchBillSplitInbox(binding)
        if (refreshAccess()?.binding != binding) return
        val sent = billSplitActions.fetchBillSplitSent(binding)
        val error = inbox.exceptionOrNull() ?: sent.exceptionOrNull() ?: ledgers.exceptionOrNull()
        val (message, tone) = when {
            error != null -> if (acknowledged == null) error.toUiText(R.string.error_generic) to MessageTone.Danger
                else UiText.res(R.string.bill_split_refresh_after_action_failed) to MessageTone.Info
            else -> acknowledged to if (acknowledged == null) MessageTone.Neutral else MessageTone.Success
        }
        updateFor(binding) {
            it.copy(
                loading = false,
                inbox = inbox.getOrNull() ?: it.inbox,
                sent = sent.getOrNull() ?: it.sent,
                candidateTargetLedgers = ledgers.getOrNull()?.toSplitTargets() ?: it.candidateTargetLedgers,
                inboxLoadState = inbox.toListLoadState(), sentLoadState = sent.toListLoadState(),
                message = message, messageTone = tone,
            )
        }
    }

    fun accept(expectedBinding: LogicalSessionBinding, publicId: String, targetLedgerId: String) = launchBound(expectedBinding) { binding ->
        complete(binding, billSplitActions.acceptBillSplitInvitation(binding, publicId, targetLedgerId),
            UiText.res(R.string.bill_split_action_accepted)) { state, row -> state.copy(inbox = state.inbox.upsertInbox(row)) }
    }

    fun reject(expectedBinding: LogicalSessionBinding, publicId: String) = launchBound(expectedBinding) { binding ->
        complete(binding, billSplitActions.rejectBillSplitInvitation(binding, publicId),
            UiText.res(R.string.bill_split_action_rejected)) { state, row -> state.copy(inbox = state.inbox.upsertInbox(row)) }
    }

    fun cancel(expectedBinding: LogicalSessionBinding, publicId: String) {
        if (refreshAccess()?.canModify != true) return
        launchBound(expectedBinding) { binding ->
            complete(binding, billSplitActions.cancelBillSplitInvitation(binding, publicId),
                UiText.res(R.string.bill_split_action_cancelled)) { state, row -> state.copy(sent = state.sent.upsertSent(row)) }
        }
    }

    private suspend fun <T> complete(
        binding: LogicalSessionBinding,
        result: Result<T>,
        message: UiText,
        adopt: (BillSplitUiState, T) -> BillSplitUiState,
    ) {
        result.onSuccess { row ->
            updateFor(binding) { adopt(it, row).copy(message = message, messageTone = MessageTone.Success) }
            if (refreshAccess()?.binding == binding) load(binding, acknowledged = message)
        }.onFailure { error ->
            updateFor(binding) { it.copy(loading = false, message = error.toUiText(R.string.error_generic), messageTone = MessageTone.Danger) }
        }
    }
}

private fun initialSplitState(actions: BillSplitActions, ledgers: BillSplitLedgerActions): BillSplitUiState {
    val access = actions.currentAccess()
    return BillSplitUiState(access = access,
        candidateTargetLedgers = if (access == null) emptyList() else ledgers.cachedLedgers().toSplitTargets())
}

private fun List<LedgerSummary>.toSplitTargets(): List<BillSplitTargetLedger> =
    filter { ledgerRoleCanModify(it.role) }.map { BillSplitTargetLedger(it.ledgerId, it.name) }

private fun <T> Result<T>.toListLoadState(): BillSplitListLoadState =
    if (isSuccess) BillSplitListLoadState.Loaded else BillSplitListLoadState.Failed

private fun List<BillSplitInbox>.upsertInbox(row: BillSplitInbox): List<BillSplitInbox> =
    if (any { it.publicId == row.publicId }) map { if (it.publicId == row.publicId) row else it } else listOf(row) + this

private fun List<BillSplitSent>.upsertSent(row: BillSplitSent): List<BillSplitSent> =
    if (any { it.publicId == row.publicId }) map { if (it.publicId == row.publicId) row else it } else listOf(row) + this
