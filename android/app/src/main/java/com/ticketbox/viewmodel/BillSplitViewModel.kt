package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitAcceptPayload
import com.ticketbox.data.repository.PendingBillSplitAcceptance
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
    val selectedTargets: Map<String, BillSplitAcceptPayload> = emptyMap(),
    val acceptances: List<PendingBillSplitAcceptance> = emptyList(),
) {
    val inboxEntryCount: Int get() = (inbox.map { it.publicId } + selectedTargets.keys +
        acceptances.map { it.payload?.publicId ?: it.row.targetId.removePrefix("bill-split:") }).distinct().size
}

class BillSplitViewModel(
    private val billSplitActions: BillSplitActions,
    private val ledgerActions: BillSplitLedgerActions,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    constructor(expenseRepository: ExpenseRepository, ledgerRepository: LedgerRepository, state: SavedStateHandle = SavedStateHandle()) : this(
        expenseBillSplitActions(expenseRepository), ledgerBillSplitActions(ledgerRepository),
        state,
    )

    private val selections = BillSplitAcceptanceDraftStore(savedStateHandle)
    private val _uiState = MutableStateFlow(initialSplitState(billSplitActions, ledgerActions).let {
        it.copy(selectedTargets = it.access?.binding?.let(selections::read).orEmpty())
    })
    val uiState: StateFlow<BillSplitUiState> = _uiState.asStateFlow()
    private var operation: Job? = null

    init {
        viewModelScope.launch { billSplitActions.observeAccess().collect { refreshAccess() } }
        viewModelScope.launch { billSplitActions.observeAcceptances().collect { observation ->
            val binding = observation.access?.binding ?: return@collect
            if (refreshAccess()?.binding != binding) return@collect
            val previous = _uiState.value.acceptances.filter { it.delivered }.map { it.row.id }.toSet()
            val delivered = observation.submissions.filter { it.delivered && it.row.id !in previous }
            observation.submissions.mapNotNull { it.payload?.publicId }.forEach { selections.remove(binding, it) }
            // The stored command receipt is displayed independently. It must never overwrite a later GET's access result.
            updateFor(binding) { state -> state.copy(acceptances = observation.submissions, selectedTargets = selections.read(binding)) }
            if (delivered.isNotEmpty()) launchBound(binding) { load(it, UiText.res(R.string.bill_split_action_accepted)) }
        } }
    }

    private fun refreshAccess(): LedgerAccessContext? {
        val access = billSplitActions.currentAccess()
        if (_uiState.value.access?.binding != access?.binding) {
            operation?.cancel()
            _uiState.value = BillSplitUiState(access = access, selectedTargets = access?.binding?.let(selections::read).orEmpty())
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

    fun selectTarget(binding: LogicalSessionBinding, publicId: String, targetLedgerId: String?) {
        if (refreshAccess()?.binding != binding || _uiState.value.acceptances.any { it.payload?.publicId == publicId }) return
        if (targetLedgerId == null) {
            selections.remove(binding, publicId)
            updateFor(binding) { it.copy(selectedTargets = selections.read(binding)) }
            return
        }
        val target = _uiState.value.candidateTargetLedgers.singleOrNull { it.ledgerId == targetLedgerId } ?: return
        val row = _uiState.value.inbox.singleOrNull { it.publicId == publicId }
        val original = _uiState.value.selectedTargets[publicId] ?: row?.let {
            BillSplitAcceptPayload(publicId = publicId, amountCents = it.amountCents,
                homeCurrencyCode = it.homeCurrencyCode, senderName = it.senderDisplayName,
                targetLedgerId = target.ledgerId, targetLedgerName = target.name)
        } ?: return
        selections.select(binding, original.copy(targetLedgerId = target.ledgerId, targetLedgerName = target.name))
        updateFor(binding) { it.copy(selectedTargets = selections.read(binding)) }
    }

    fun accept(expectedBinding: LogicalSessionBinding, publicId: String, targetLedgerId: String) {
        if (refreshAccess()?.binding != expectedBinding || _uiState.value.acceptances.any { it.payload?.publicId == publicId }) return
        if (_uiState.value.selectedTargets[publicId] == null) selectTarget(expectedBinding, publicId, targetLedgerId)
        val original = _uiState.value.selectedTargets[publicId]?.takeIf { it.targetLedgerId == targetLedgerId } ?: return
        launchBound(expectedBinding) { binding ->
            val result = billSplitActions.acceptBillSplitInvitation(binding, original)
            if (result.isSuccess) selections.remove(binding, publicId)
            updateFor(binding) { it.copy(loading = false, selectedTargets = selections.read(binding),
                message = result.exceptionOrNull()?.toUiText(R.string.error_generic) ?: UiText.res(R.string.bill_split_accept_queued),
                messageTone = if (result.isSuccess) MessageTone.Info else MessageTone.Danger) }
        }
    }

    fun recoverAcceptance(binding: LogicalSessionBinding, id: Long, drop: Boolean) = launchBound(binding) {
        val result = billSplitActions.recoverAcceptance(it, id, drop)
        updateFor(it) { state -> state.copy(loading = false,
            message = result.exceptionOrNull()?.toUiText(R.string.error_generic), messageTone = MessageTone.Danger) }
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
