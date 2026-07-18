package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitLedgerActions
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0029 bill split inbox / sent UI.
 *
 * State is two parallel lists + a transient ``message`` for action
 * results. Actions mutate the lists and return the new lists; we don't
 * do optimistic updates because invitation state transitions are
 * relatively rare and the server is the source of truth.
 *
 * Also owns ``candidateTargetLedgers``: the writable ledgers an
 * inbox row can be accepted into — id (the API value) AND display name
 * (audit P3 #3: the screen used to print the internal ledger_id on the
 * accept button, ENGINEERING_RULES §3 forbids surfacing ids). Computed
 * from a fresh ``refreshLedgers()`` call so a fresh install / cold start
 * doesn't leave the accept action disabled because cache was empty
 * (codex P2 review, PR #88).
 */
data class BillSplitTargetLedger(
    val ledgerId: String,
    val name: String,
)

enum class BillSplitListLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

data class BillSplitUiState(
    val canModify: Boolean = true,
    val inbox: List<BillSplitInbox> = emptyList(),
    val sent: List<BillSplitSent> = emptyList(),
    val candidateTargetLedgers: List<BillSplitTargetLedger> = emptyList(),
    val inboxLoadState: BillSplitListLoadState = BillSplitListLoadState.Unknown,
    val sentLoadState: BillSplitListLoadState = BillSplitListLoadState.Unknown,
    val loading: Boolean = false,
    val message: UiText? = null,
)

class BillSplitViewModel(
    private val billSplitActions: BillSplitActions,
    private val ledgerActions: BillSplitLedgerActions,
) : ViewModel() {

    constructor(
        expenseRepository: ExpenseRepository,
        ledgerRepository: LedgerRepository,
    ) : this(
        expenseBillSplitActions(expenseRepository),
        ledgerBillSplitActions(ledgerRepository),
    )

    private val _uiState = MutableStateFlow(
        BillSplitUiState(
            canModify = billSplitActions.canModifyLedger(),
            candidateTargetLedgers = ledgerActions.cachedLedgers()
                .filter { ledgerRoleCanModify(it.role) }
                .map { BillSplitTargetLedger(ledgerId = it.ledgerId, name = it.name) },
        ),
    )
    val uiState: StateFlow<BillSplitUiState> = _uiState.asStateFlow()

    fun refresh() {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    canModify = billSplitActions.canModifyLedger(),
                    loading = true,
                    inboxLoadState = BillSplitListLoadState.Loading,
                    sentLoadState = BillSplitListLoadState.Loading,
                    message = null,
                )
            }
            // Refresh ledger membership in parallel so the accept-target
            // dropdown is never empty just because cache was cold. Failure
            // is non-fatal — we fall back to whatever cache held.
            ledgerActions.refreshLedgers()
                .onSuccess { ledgers ->
                    _uiState.update {
                        it.copy(
                            candidateTargetLedgers = ledgers
                                .filter { l -> ledgerRoleCanModify(l.role) }
                                .map { l -> BillSplitTargetLedger(ledgerId = l.ledgerId, name = l.name) },
                        )
                    }
                }
            val inboxResult = billSplitActions.fetchBillSplitInbox()
            val sentResult = billSplitActions.fetchBillSplitSent()
            _uiState.update {
                it.copy(
                    canModify = billSplitActions.canModifyLedger(),
                    loading = false,
                    inbox = inboxResult.getOrNull() ?: it.inbox,
                    sent = sentResult.getOrNull() ?: it.sent,
                    inboxLoadState = inboxResult.toListLoadState(),
                    sentLoadState = sentResult.toListLoadState(),
                    message = (inboxResult.exceptionOrNull() ?: sentResult.exceptionOrNull())
                        ?.toUiText(R.string.error_generic),
                )
            }
        }
    }

    fun accept(publicId: String, targetLedgerId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            billSplitActions.acceptBillSplitInvitation(publicId, targetLedgerId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.toUiText(R.string.error_generic)) }
                }
        }
    }

    fun reject(publicId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            billSplitActions.rejectBillSplitInvitation(publicId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.toUiText(R.string.error_generic)) }
                }
        }
    }

    fun cancel(publicId: String) {
        if (!billSplitActions.canModifyLedger()) {
            _uiState.update {
                it.copy(
                    canModify = false,
                    loading = false,
                    message = UiText.res(R.string.common_readonly_ledger),
                )
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            billSplitActions.cancelBillSplitInvitation(publicId)
                .onSuccess { refresh() }
                .onFailure { err ->
                    _uiState.update { it.copy(loading = false, message = err.toUiText(R.string.error_generic)) }
                }
        }
    }
}

private fun <T> Result<T>.toListLoadState(): BillSplitListLoadState =
    if (isSuccess) BillSplitListLoadState.Loaded else BillSplitListLoadState.Failed
