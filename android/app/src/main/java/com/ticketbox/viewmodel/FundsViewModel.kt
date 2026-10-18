package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.FundsOverviewDto
import com.ticketbox.data.remote.dto.ExpenseFundingViewDto
import com.ticketbox.data.remote.dto.InstallmentsDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.FundsInputState
import com.ticketbox.data.repository.FundsRepository
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.coroutineScope
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class FundsUiState(val access: LedgerAccessContext? = null, val accounts: List<FinancialAccountDto> = emptyList(),
    val detail: FinancialAccountDto? = null, val task: FundsInputState = FundsInputState(null),
    val editing: Boolean = false, val loading: Boolean = false, val busy: Boolean = false,
    val fromCache: Boolean = false, val error: UiText? = null, val overview: FundsOverviewDto? = null,
    val funding: ExpenseFundingViewDto? = null, val fundingPage: Boolean = false, val installments: InstallmentsDto? = null,
    val accountChoices: List<com.ticketbox.data.remote.dto.AccountChoiceDto> = emptyList(),
    val existingDebts: List<com.ticketbox.data.remote.dto.ExistingDebtChoiceDto> = emptyList(),
    val captureRequested: Boolean = false,
    val repaymentCapture: com.ticketbox.domain.model.RepaymentDraft? = null,
    val envelopeMonth: String? = null, val envelopes: com.ticketbox.data.remote.dto.EnvelopesDto? = null,
    val envelopeHistory: List<com.ticketbox.data.remote.dto.EnvelopeRevisionDto>? = null,
    val envelopeHistoryBusy: Boolean = false, val envelopeHistoryMore: Boolean = false)

class FundsViewModel(internal val repository: FundsRepository, internal val expenseId: Long? = null,
    internal val repaymentDraftId: String? = null,
    internal val captures: com.ticketbox.data.repository.RepaymentDraftActions? = null) : ViewModel() {
    // Synchronous editor state prevents delayed flow emissions from replacing newer IME input.
    // Room remains the durable raw-input owner.
    internal val mutable = mutableStateOf(FundsUiState())
    val state: State<FundsUiState> = mutable

    private val writes = Mutex()
    init {
        viewModelScope.launch {
            repository.readAccessDenials.collect { denial ->
                if (mutable.value.access?.binding == denial.binding) mutable.value = mutable.value.copy(
                    accounts = emptyList(), detail = null, overview = null, funding = null, installments = null,
                    existingDebts = emptyList(), repaymentCapture = null, envelopes = null, envelopeHistory = null,
                    loading = false, fromCache = false, error = denial.failure.toUiText())
            }
        }
        viewModelScope.launch {
            repository.access().collectLatest { access ->
                mutable.value = FundsUiState(access = access, fundingPage = expenseId != null, captureRequested = repaymentDraftId != null)
                if (access != null) coroutineScope {
                    launch {
                        repository.input(access.binding).collect { original ->
                            if (mutable.value.access?.binding == access.binding) mutable.value = mutable.value.let { current ->
                                val preserveTyping = current.task.input?.key == original.input?.key && !original.frozen
                                current.copy(task = if (preserveTyping) original.copy(input = current.task.input) else original)
                            }
                        }
                    }
                    refreshAccounts(access.binding)
                }
            }
        }
    }


    fun refresh() { state.value.access?.binding?.let { binding -> viewModelScope.launch {
        val month = state.value.envelopeMonth
        if (month != null) refreshEnvelopes(binding, month) else {
            val id = state.value.detail?.publicId
            refreshAccounts(binding)
            if (id != null && state.value.access?.binding == binding && state.value.detail?.publicId == id) open(id)
        }
    } } }
    fun open(id: String, forCapture: Boolean = false) {
        val binding = state.value.access?.binding ?: return
        viewModelScope.launch {
            val result = repository.reads.detail(binding, id)
            if (state.value.access?.binding == binding) result.fold(
                onSuccess = { read ->
                    mutable.value = mutable.value.copy(detail = read.value, fromCache = read.fromCache, editing = false, error = null, installments = null)
                    if (read.value.kind == "credit") repository.reads.installments(binding, id).fold(
                        onSuccess = { schedule -> if (state.value.access?.binding == binding && state.value.detail?.publicId == id)
                            mutable.value = mutable.value.copy(installments = schedule.value, fromCache = mutable.value.fromCache || schedule.fromCache) },
                        onFailure = { error -> if (state.value.access?.binding == binding) mutable.value = mutable.value.copy(error = error.toUiText()) })
                    if (forCapture && state.value.access?.binding == binding && state.value.repaymentCapture?.isPending == true) start("repay")
                },
                onFailure = { error -> mutable.value = mutable.value.copy(error = error.toUiText()) })
        }
    }


    fun edit(change: (FundsInput) -> FundsInput) {
        val current = state.value
        val old = current.task.input ?: return
        if (current.task.frozen || current.busy || old.binding != current.access?.binding || current.access.canModify.not()) return
        val value = change(old)
        mutable.value = mutable.value.copy(task = mutable.value.task.copy(input = value), error = null)
        save(value)
    }

    internal fun save(value: FundsInput) {
        viewModelScope.launch { writes.withLock {
            repository.save(value).onFailure { error -> if (state.value.access?.binding == value.binding) mutable.value = mutable.value.copy(error = error.toUiText()) }
        } }
    }


    fun back(): Boolean {
        if (state.value.editing) { mutable.value = mutable.value.copy(editing = false); return true }
        if (state.value.envelopeMonth != null) {
            mutable.value = mutable.value.copy(envelopeMonth = null, envelopes = null); refresh(); return true
        }
        if (state.value.detail != null) { mutable.value = mutable.value.copy(detail = null); refresh(); return true }
        return false
    }

    fun resume() {
        mutable.value = mutable.value.copy(editing = true)
        val input = state.value.task.input ?: return
        if (input.mode == "envelopes") { openEnvelopes(input.envelopeMonth); return }
        if (input.accountId.isBlank()) return
        viewModelScope.launch { reloadTaskAccount(input.binding, input.accountId) }
    }


    fun submit() = runAction { binding -> repository.submit(binding).map { Unit } }
    fun retry() = runAction { repository.retry(it) }
    fun review() = runAction { binding ->
        val fresh = repository.reads.accounts(binding).getOrThrow()
        if (fresh.fromCache) {
            mutable.value = mutable.value.copy(error = UiText.res(R.string.funds_network_required))
            return@runAction Result.success(Unit)
        }
        repository.review(binding, fresh.value).onSuccess {
            state.value.task.input?.accountId?.takeIf(String::isNotBlank)?.let { reloadTaskAccount(binding, it) }
        }
    }
    fun finish() = runAction { binding ->
        val continueCapture = state.value.captureRequested && state.value.task.input?.mode == "create"
        val accountId = state.value.task.input?.accountId?.takeIf(String::isNotBlank)
        repository.finish(binding).onSuccess {
        if (state.value.access?.binding != binding) return@onSuccess
        mutable.value = mutable.value.copy(task = FundsInputState(null), editing = false, detail = null, captureRequested = continueCapture)
        val month = state.value.envelopeMonth
        if (month != null) refreshEnvelopes(binding, month) else refreshAccounts(binding)
        if (month == null && accountId != null && state.value.access?.binding == binding) open(accountId)
    } }

    private fun runAction(action: suspend (LogicalSessionBinding) -> Result<Unit>) {
        val binding = state.value.access?.binding ?: return
        if (state.value.busy) return
        mutable.value = mutable.value.copy(busy = true, error = null)
        viewModelScope.launch {
            try { writes.withLock { action(binding).getOrThrow() } }
            catch (cancelled: kotlinx.coroutines.CancellationException) { throw cancelled }
            catch (error: Exception) {
                com.ticketbox.data.repository.logNetworkWarning("Funds action failed", error)
                if (state.value.access?.binding == binding) mutable.value = mutable.value.copy(error = error.toUiText())
            }
            finally { if (state.value.access?.binding == binding) mutable.value = mutable.value.copy(busy = false) }
        }
    }
}
