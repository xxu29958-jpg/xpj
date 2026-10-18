package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class FundsUiState(val access: LedgerAccessContext? = null, val accounts: List<FinancialAccountDto> = emptyList(),
    val detail: FinancialAccountDto? = null, val task: FundsInputState = FundsInputState(null),
    val editing: Boolean = false, val loading: Boolean = false, val busy: Boolean = false,
    val fromCache: Boolean = false, val error: String? = null, val overview: FundsOverviewDto? = null,
    val funding: ExpenseFundingViewDto? = null, val fundingPage: Boolean = false, val installments: InstallmentsDto? = null,
    val accountChoices: List<com.ticketbox.data.remote.dto.AccountChoiceDto> = emptyList(),
    val existingDebts: List<com.ticketbox.data.remote.dto.ExistingDebtChoiceDto> = emptyList())

class FundsViewModel(internal val repository: FundsRepository, internal val expenseId: Long? = null) : ViewModel() {
    internal val mutable = MutableStateFlow(FundsUiState())
    val state = mutable.asStateFlow()
    private val writes = Mutex()
    init {
        viewModelScope.launch {
            repository.access().collectLatest { access ->
                mutable.value = FundsUiState(access = access, fundingPage = expenseId != null)
                if (access != null) coroutineScope {
                    launch {
                        repository.input(access.binding).collect { original ->
                            if (mutable.value.access?.binding == access.binding) mutable.update { current ->
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


    fun refresh() { state.value.access?.binding?.let { viewModelScope.launch { refreshAccounts(it) } } }
    fun open(id: String) {
        val binding = state.value.access?.binding ?: return
        viewModelScope.launch {
            val result = repository.reads.detail(binding, id)
            if (state.value.access?.binding == binding) result.fold(
                onSuccess = { read ->
                    mutable.update { it.copy(detail = read.value, fromCache = read.fromCache, editing = false, error = null, installments = null) }
                    if (read.value.kind == "credit") repository.reads.installments(binding, id).fold(
                        onSuccess = { schedule -> if (state.value.access?.binding == binding && state.value.detail?.publicId == id)
                            mutable.update { it.copy(installments = schedule.value, fromCache = it.fromCache || schedule.fromCache) } },
                        onFailure = { error -> if (state.value.access?.binding == binding) mutable.update { it.copy(error = error.message) } })
                },
                onFailure = { error -> mutable.update { it.copy(error = error.message) } })
        }
    }


    fun edit(change: (FundsInput) -> FundsInput) {
        val current = state.value
        val old = current.task.input ?: return
        if (current.task.frozen || current.busy || old.binding != current.access?.binding || current.access.canModify.not()) return
        val value = change(old)
        mutable.update { it.copy(task = it.task.copy(input = value), error = null) }
        save(value)
    }

    internal fun save(value: FundsInput) {
        viewModelScope.launch { writes.withLock {
            repository.save(value).onFailure { error -> if (state.value.access?.binding == value.binding) mutable.update { it.copy(error = error.message) } }
        } }
    }


    fun back(): Boolean {
        if (state.value.editing) { mutable.update { it.copy(editing = false) }; return true }
        if (state.value.detail != null) { mutable.update { it.copy(detail = null) }; refresh(); return true }
        return false
    }

    fun resume() {
        mutable.update { it.copy(editing = true) }
        val input = state.value.task.input ?: return
        if (input.accountId.isBlank()) return
        viewModelScope.launch { reloadSchedule(input.binding, input.accountId) }
    }


    fun submit() = runAction { binding -> repository.submit(binding).map { Unit } }
    fun retry() = runAction { repository.retry(it) }
    fun review() = runAction { binding ->
        val fresh = repository.reads.accounts(binding).getOrThrow()
        require(!fresh.fromCache) { "请联网核对最新账户；原输入已保留。" }
        repository.review(binding, fresh.value).onSuccess {
            state.value.task.input?.accountId?.takeIf(String::isNotBlank)?.let { reloadSchedule(binding, it) }
        }
    }
    fun finish() = runAction { binding -> repository.finish(binding).onSuccess {
        mutable.update { it.copy(task = FundsInputState(null), editing = false, detail = null) }
        refreshAccounts(binding)
    } }

    private fun runAction(action: suspend (LogicalSessionBinding) -> Result<Unit>) {
        val binding = state.value.access?.binding ?: return
        if (state.value.busy) return
        mutable.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try { writes.withLock { action(binding).getOrThrow() } }
            catch (cancelled: kotlinx.coroutines.CancellationException) { throw cancelled }
            catch (error: Exception) { if (state.value.access?.binding == binding) mutable.update { it.copy(error = error.message) } }
            finally { if (state.value.access?.binding == binding) mutable.update { it.copy(busy = false) } }
        }
    }
}
