package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.squareup.moshi.JsonClass
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.isValidPayDay
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import java.time.YearMonth

/** Income plan listing, forecast and durable submission recovery. */
data class IncomePlanUiState(
    val history: IncomeHistoryState = IncomeHistoryState(),
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
    val archivedFetchedAt: String? = null,
    val archivedFromCache: Boolean = false,
    val isLoading: Boolean = false,
    val loadState: IncomePlanLoadState = IncomePlanLoadState.Unknown,
    val canModify: Boolean = true,
    val activePlans: List<IncomePlan> = emptyList(),
    val archivedPlans: List<IncomePlan> = emptyList(),
    val scheduledAmountCents: Long? = null,
    val forecastMonth: String? = null,
    val forecastCurrencyCode: String? = null,
    val missingCurrencyCodes: List<String> = emptyList(),
    val referenceRates: List<com.ticketbox.domain.model.CurrencyReferenceRate> = emptyList(),
    val pendingSubmissions: List<PendingIncomePlanSubmission> = emptyList(),
    val selectedSubmissionId: Long? = null,
    val binding: LogicalSessionBinding? = null,
    val currentMonthSummary: IncomePlanMonthSummary = IncomePlanMonthSummary(),
    val error: UiText? = null,
    val flashMessage: UiText? = null,
)

enum class IncomePlanLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

/** Confirmed forecast values supplied by the IncomePlan query owner. */
data class IncomePlanMonthSummary(
    val effectivePlanCount: Int = 0,
    val expectedAmountCents: Long? = null,
)

@JsonClass(generateAdapter = true)
data class IncomePlanDraftUi(
    val intentMonth: String = YearMonth.now().toString(),
    val label: String = "",
    val sourceType: IncomeSourceType = IncomeSourceType.SALARY,
    val frequency: IncomeFrequency = IncomeFrequency.ONE_TIME,
    val incomeMonthInput: String = YearMonth.now().toString(),
    val amountYuanInput: String = "",
    val payDayInput: String = "10",
    @Transient val validationError: UiText? = null,
    /** 账本币种（R12-D）：VM 由列表信封 capability 注入；null=未确认 → parsedAmountCents 归
     *  null → isValid false → 禁写（不落 CNY 兜底）。 */
    val homeCurrency: CurrencyCode? = null,
) {
    val isValid: Boolean
        get() = intentMonth.isNotEmpty() && label.trim().isNotEmpty() &&
            parsedAmountCents() != null &&
            parsedPayDay() != null &&
            (frequency == IncomeFrequency.MONTHLY || parsedIncomeMonth() != null)

    // 元→分走共享精确 BigDecimal 解析器（§3 禁 Double 存金额），按账本币种扩位（R12-D：
    // 零小数 home 不 ×100；未确认 → null 禁写）。允许 0、拒负，不做 HALF_UP 改写。
    fun parsedAmountCents(): Long? {
        if (amountYuanInput.trim().startsWith('-')) return null
        val currency = homeCurrency ?: return null
        return parseAmountCents(amountYuanInput, currency)?.takeIf { it >= 0 }
    }

    fun parsedPayDay(): Int? {
        val day = payDayInput.trim().toIntOrNull() ?: return null
        return if (day.isValidPayDay()) day else null
    }

    fun parsedIncomeMonth(): String? {
        val text = incomeMonthInput.trim()
        return runCatching { YearMonth.parse(text).toString() }.getOrNull()
    }
}

class IncomePlanViewModel(
    private val repository: IncomePlanActions,
    private val onDataChanged: () -> Unit = {},
) : ViewModel() {

    private val _state = MutableStateFlow(IncomePlanUiState(canModify = false))
    val state: StateFlow<IncomePlanUiState> = _state.asStateFlow()
    private var bindingGeneration = 0
    private var refreshGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var activeCanModify = false
    private var queueJob: Job? = null
    private var requestedSubmissionId: Long? = null
    private var readDenial: com.ticketbox.data.repository.SnapshotAccessDenial? = null
    private val history = IncomeHistoryTask(repository::history, viewModelScope, { activeBinding }) { result ->
        _state.update { it.copy(history = result) }
    }

    fun openHistory(publicId: String) {
        if ((_state.value.activePlans + _state.value.archivedPlans).any { it.publicId == publicId }) history.open(publicId)
    }
    fun dismissHistory() = history.dismiss()
    fun moreHistory() = history.more()
    fun retryHistory() = history.retry()

    init {
        viewModelScope.launch {
            repository.readAccessDenials.collect { denied ->
                readDenial = denied
                if (denied.binding == activeBinding) retireReadData(denied.failure)
            }
        }
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    activeCanModify = access?.canModify ?: false
                    if (activeBinding == access?.binding) {
                        _state.update { it.copy(canModify = activeCanModify) }
                        return@collect
                    }
                    val selected = requestedSubmissionId.takeIf { activeBinding == null }
                    requestedSubmissionId = null
                    activeBinding = access?.binding
                    history.dismiss()
                    bindingGeneration += 1
                    _state.value = IncomePlanUiState(canModify = activeCanModify, binding = activeBinding,
                        selectedSubmissionId = selected)
                    queueJob?.cancel()
                    if (access != null) {
                        readDenial?.takeIf { it.binding == access.binding }?.let { retireReadData(it.failure) }
                        queueJob = viewModelScope.launch {
                            var completed = emptySet<Long>()
                            repository.observeSubmissions(access.binding).collect { rows ->
                                if (activeBinding != access.binding) return@collect
                                val done = rows.filter { it.isConfirmed }.map { it.row.id }.toSet()
                                _state.update { it.copy(pendingSubmissions = rows) }
                                if ((done - completed).isNotEmpty()) { onDataChanged(); refresh() }
                                completed = done
                            }
                        }
                        refresh()
                    }
                }
        }
    }

    fun openSubmission(originalSubmissionId: Long) {
        if (activeBinding == null) requestedSubmissionId = originalSubmissionId
        _state.update { it.copy(selectedSubmissionId = originalSubmissionId) }
    }

    fun refresh() {
        val expectedBinding = activeBinding ?: return
        history.refresh()
        val binding = bindingGeneration
        val refresh = ++refreshGeneration
        _state.update {
            it.copy(
                isLoading = true,
                loadState = IncomePlanLoadState.Loading,
                error = null,
            )
        }
        viewModelScope.launch {
            val active = repository.listActive(expectedBinding)
            val archived = repository.listIncluding(
                expectedBinding,
                com.ticketbox.domain.model.IncomePlanStatus.ARCHIVED,
            )
            if (binding != bindingGeneration || refresh != refreshGeneration) return@launch
            val refusal = listOfNotNull(active.exceptionOrNull(), archived.exceptionOrNull()).firstOrNull { it.isReadAccessDenied() }
            if (refusal != null) { retireReadData(refusal); return@launch }
            val archivedRead = archived.getOrNull()
            val nextState = active.fold(
                onSuccess = { listing ->
                    val archivedError = archived.exceptionOrNull()?.toUiText(R.string.income_plan_archived_load_failed)
                    _state.value.copy(
                        isLoading = false,
                        loadState = IncomePlanLoadState.Loaded,
                        canModify = activeCanModify,
                        activePlans = listing.plans,
                        archivedPlans = archivedRead?.value ?: _state.value.archivedPlans,
                        fetchedAt = listing.fetchedAt, fromCache = listing.fromCache,
                        archivedFetchedAt = archivedRead?.fetchedAt ?: _state.value.archivedFetchedAt,
                        archivedFromCache = archivedRead?.fromCache ?: _state.value.archivedFromCache,
                        scheduledAmountCents = listing.scheduledAmountCents,
                        forecastMonth = listing.month,
                        forecastCurrencyCode = listing.homeCurrencyCode,
                        missingCurrencyCodes = listing.missingCurrencyCodes,
                        referenceRates = listing.referenceRates,
                        currentMonthSummary = IncomePlanMonthSummary(listing.effectivePlanCount, listing.expectedAmountCents),
                        error = archivedError,
                    )
                },
                onFailure = { err ->
                    _state.value.copy(
                        isLoading = false,
                        loadState = IncomePlanLoadState.Failed,
                        archivedPlans = archivedRead?.value ?: _state.value.archivedPlans,
                        archivedFetchedAt = archivedRead?.fetchedAt ?: _state.value.archivedFetchedAt,
                        archivedFromCache = archivedRead?.fromCache ?: _state.value.archivedFromCache,
                        error = err.toUiText(R.string.income_plan_load_failed),
                    )
                },
            )
            if (binding == bindingGeneration && refresh == refreshGeneration) {
                _state.value = nextState
            }
        }
    }

    private fun retireReadData(error: Throwable) {
        refreshGeneration += 1
        history.dismiss()
        _state.update { it.copy(isLoading = false, loadState = IncomePlanLoadState.Failed,
            activePlans = emptyList(), archivedPlans = emptyList(), fetchedAt = null, fromCache = false,
            archivedFetchedAt = null, archivedFromCache = false, forecastMonth = null, forecastCurrencyCode = null,
            scheduledAmountCents = null, currentMonthSummary = IncomePlanMonthSummary(),
            referenceRates = emptyList(), missingCurrencyCodes = emptyList(), error = error.toUiText(R.string.income_plan_load_failed)) }
    }

    fun recoverSubmission(pending: PendingIncomePlanSubmission, drop: Boolean) {
        val binding = activeBinding ?: return
        if (pending !in _state.value.pendingSubmissions) return
        viewModelScope.launch {
            repository.recoverSubmission(binding, pending, drop).onFailure { error ->
                if (activeBinding == binding) _state.update { it.copy(error = error.toUiText(R.string.error_generic)) }
            }
        }
    }

    fun restore(publicId: String, expectedRowVersion: Long) {
        val expectedBinding = activeBinding ?: return
        val intentMonth = _state.value.forecastMonth ?: return
        val binding = bindingGeneration
        viewModelScope.launch {
            val result = repository.restore(expectedBinding, publicId, expectedRowVersion, intentMonth)
            if (binding != bindingGeneration) return@launch
            result.fold(
                onSuccess = {
                    _state.update { it.copy(flashMessage = UiText.res(R.string.income_plan_restored)) }
                    onDataChanged()
                    refresh()
                },
                onFailure = { err ->
                    _state.update { it.copy(error = err.toUiText(R.string.error_generic)) }
                },
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }
}
