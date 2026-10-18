package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.FundsOverviewDto
import com.ticketbox.data.remote.dto.ExpenseFundingViewDto
import com.ticketbox.data.repository.fundingInputs
import com.ticketbox.data.remote.dto.InstallmentsDto
import com.ticketbox.data.remote.dto.InstallmentViewDto
import com.ticketbox.data.repository.InstallmentInputWire
import com.ticketbox.data.repository.InstallmentPeriodInput
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.FundsInputState
import com.ticketbox.data.repository.FundsRepository
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import java.time.LocalDate
import java.util.UUID
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

class FundsViewModel(private val repository: FundsRepository, private val expenseId: Long? = null) : ViewModel() {
    private val mutable = MutableStateFlow(FundsUiState())
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

    private suspend fun refreshAccounts(binding: LogicalSessionBinding) {
        mutable.update { it.copy(loading = true) }
        val result = repository.accounts(binding)
        if (mutable.value.access?.binding != binding) return
        result.fold(onSuccess = { read -> mutable.update { it.copy(accounts = read.value, fromCache = read.fromCache, loading = false, error = null) } },
            onFailure = { error -> mutable.update { it.copy(loading = false, error = error.message) } })
        val choices = repository.accountChoices(binding)
        if (mutable.value.access?.binding != binding) return
        choices.onSuccess { read -> mutable.update { it.copy(accountChoices = read.value) } }
        val existing = repository.existingDebts(binding)
        if (mutable.value.access?.binding != binding) return
        existing.fold(onSuccess = { read -> mutable.update { it.copy(existingDebts = read.value, fromCache = it.fromCache || read.fromCache) } },
            onFailure = { error -> mutable.update { it.copy(error = error.message) } })
        if (expenseId != null) {
            val funding = repository.funding(binding, expenseId)
            if (mutable.value.access?.binding == binding) funding.fold(
                onSuccess = { read -> mutable.update { it.copy(funding = read.value, fromCache = it.fromCache || read.fromCache) } },
                onFailure = { error -> mutable.update { it.copy(funding = null, error = error.message) } })
            return
        }
        val overview = repository.overview(binding)
        if (mutable.value.access?.binding == binding) overview.fold(
            onSuccess = { read -> mutable.update { it.copy(overview = read.value, fromCache = it.fromCache || read.fromCache) } },
            onFailure = { error -> mutable.update { it.copy(overview = null, error = error.message) } })
    }

    fun refresh() { state.value.access?.binding?.let { viewModelScope.launch { refreshAccounts(it) } } }
    fun open(id: String) {
        val binding = state.value.access?.binding ?: return
        viewModelScope.launch {
            val result = repository.detail(binding, id)
            if (state.value.access?.binding == binding) result.fold(
                onSuccess = { read ->
                    mutable.update { it.copy(detail = read.value, fromCache = read.fromCache, editing = false, error = null, installments = null) }
                    if (read.value.kind == "credit") repository.installments(binding, id).fold(
                        onSuccess = { schedule -> if (state.value.access?.binding == binding && state.value.detail?.publicId == id)
                            mutable.update { it.copy(installments = schedule.value, fromCache = it.fromCache || schedule.fromCache) } },
                        onFailure = { error -> if (state.value.access?.binding == binding) mutable.update { it.copy(error = error.message) } })
                },
                onFailure = { error -> mutable.update { it.copy(error = error.message) } })
        }
    }

    fun start(mode: String) {
        val current = state.value
        val access = current.access?.takeIf { it.canModify } ?: return
        if (current.task.input != null) { mutable.update { it.copy(editing = true) }; return }
        if (mode == "funding") {
            val source = current.funding?.takeIf { it.canEdit } ?: return
            val value = FundsInput(access.binding, mode, UUID.randomUUID().toString(),
                expenseId = source.expenseId, version = source.expenseRowVersion, currency = source.currencyCode,
                fundingJson = fundingInputs(source), note = if (source.parts.isEmpty()) "补充付款来源" else "更正付款来源")
            mutable.update { it.copy(task = FundsInputState(value), editing = true, error = null) }
            save(value)
            return
        }
        val account = current.detail
        val currency = if (mode == "create") current.overview?.homeCurrencyCode.orEmpty() else account?.currencyCode.orEmpty()
        fun amount(value: Long?) = value?.let {
            java.math.BigDecimal.valueOf(it, com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(currency)?.minorUnitDigits ?: return@let "").toPlainString()
        }.orEmpty()
        val terms = account?.creditTerms?.takeIf { mode == "edit" }
        val value = FundsInput(access.binding, mode, UUID.randomUUID().toString(),
            accountId = if (mode == "create") "" else account?.publicId.orEmpty(), version = account?.rowVersion ?: 0,
            calendarRevision = account?.calendarRevision ?: 0, name = if (mode == "create") "" else account?.name.orEmpty(),
            kind = account?.kind ?: "bank", currency = currency,
            visibility = account?.visibility ?: "private", institution = account?.institution.orEmpty(), tail = account?.tail.orEmpty(),
            archived = account?.archived ?: false, date = LocalDate.now().toString(), loanCurrency = account?.currencyCode.orEmpty(),
            creditLimit = amount(terms?.creditLimitMinor), availableCredit = amount(terms?.availableCreditMinor),
            creditObservedOn = terms?.observedOn.orEmpty(), creditSource = terms?.source.orEmpty(),
            statementDay = terms?.statementDay?.toString().orEmpty(), paymentDueDay = terms?.paymentDueDay?.toString().orEmpty())
        mutable.update { it.copy(task = FundsInputState(value), editing = true, error = null) }
        save(value)
    }

    fun edit(change: (FundsInput) -> FundsInput) {
        val current = state.value
        val old = current.task.input ?: return
        if (current.task.frozen || current.busy || old.binding != current.access?.binding || current.access.canModify.not()) return
        val value = change(old)
        mutable.update { it.copy(task = it.task.copy(input = value), error = null) }
        save(value)
    }

    private fun save(value: FundsInput) {
        viewModelScope.launch { writes.withLock {
            repository.save(value).onFailure { error -> if (state.value.access?.binding == value.binding) mutable.update { it.copy(error = error.message) } }
        } }
    }

    fun choosePayer(account: FinancialAccountDto) = edit { it.copy(payerId = account.publicId, payerName = account.name,
        payerCurrency = account.currencyCode, payerVersion = account.rowVersion) }

    fun voidPayment(id: String) {
        if (state.value.task.input != null) { resume(); return }
        start("void_repayment")
        edit { it.copy(repaymentId = id) }
    }

    fun reviseAgreement(agreement: InstallmentViewDto) {
        if (state.value.task.input != null) { resume(); return }
        start("installments")
        val current = state.value
        val currency = com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(current.task.input?.currency) ?: return
        fun amount(value: Long) = java.math.BigDecimal.valueOf(value, currency.minorUnitDigits).toPlainString()
        edit { input -> input.copy(name = agreement.name, source = "", previousAgreement = agreement.publicId,
            drawIds = current.installments?.draws.orEmpty().filter { it.publicId in agreement.drawPublicIds && it.remainingMinor > 0 }.map { it.publicId },
            periodsJson = InstallmentInputWire.periods.toJson(agreement.periods.filter { it.principalMinor > it.paidPrincipalMinor }.map {
                InstallmentPeriodInput(it.dueOn, amount(it.principalMinor - it.paidPrincipalMinor), amount(it.plannedFeeMinor - it.paidFeeMinor)) })) }
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

    private suspend fun reloadSchedule(binding: LogicalSessionBinding, accountId: String) {
        val target = repository.detail(binding, accountId).getOrNull()?.value ?: return
        if (target.kind != "credit") return
        repository.installments(binding, accountId).fold(
            onSuccess = { read -> if (state.value.access?.binding == binding && state.value.task.input?.accountId == accountId)
                mutable.update { it.copy(installments = read.value, fromCache = it.fromCache || read.fromCache) } },
            onFailure = { error -> if (state.value.access?.binding == binding) mutable.update { it.copy(error = error.message) } })
    }
    fun submit() = runAction { binding -> repository.submit(binding).map { Unit } }
    fun retry() = runAction { repository.retry(it) }
    fun review() = runAction { binding ->
        val fresh = repository.accounts(binding).getOrThrow()
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
