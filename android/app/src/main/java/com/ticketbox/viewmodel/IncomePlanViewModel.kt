package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.PendingIncomePlanEdit
import com.ticketbox.data.local.PendingMutationStatus
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

/**
 * v1.1 income plan screen state + actions.
 *
 * UI pattern follows the Android secondary-page guidance: summary →
 * row groups → bottom-sheet add form. ViewModel keeps draft + validation
 * state so the bottom sheet stays a pure render.
 */
data class IncomePlanUiState(
    val isLoading: Boolean = false,
    val loadState: IncomePlanLoadState = IncomePlanLoadState.Unknown,
    val canModify: Boolean = true,
    val activePlans: List<IncomePlan> = emptyList(),
    val archivedPlans: List<IncomePlan> = emptyList(),
    val scheduledAmountCents: Long? = null,
    val forecastMonth: String? = null,
    val forecastCurrencyCode: String? = null,
    val missingCurrencyCodes: List<String> = emptyList(),
    val pendingEdits: List<PendingIncomePlanEdit> = emptyList(),
    val currentMonthSummary: IncomePlanMonthSummary = IncomePlanMonthSummary(),
    val error: UiText? = null,
    val addDraft: IncomePlanDraftUi = IncomePlanDraftUi(intentMonth = "", incomeMonthInput = ""),
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    /**
     * 一次性信号：[submitDraft] 真正成功后置 true；底部抽屉屏只在它为 true 时关闭（关时调
     * [resetDraft] 一并清掉本信号 + 草稿，镜像 LedgerViewModel.manualCreateDone 的 ack 约定）。
     * failure 不置位 → 抽屉保留、表单错误可见（修「乐观关闭」：旧逻辑按本地 `addDraft.isValid`
     * 关闭、无视 create() 结果，后端失败时静默丢失）。
     */
    val addSucceeded: Boolean = false,
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

data class IncomePlanDraftUi(
    val intentMonth: String = YearMonth.now().toString(),
    val label: String = "",
    val sourceType: IncomeSourceType = IncomeSourceType.SALARY,
    val frequency: IncomeFrequency = IncomeFrequency.ONE_TIME,
    val incomeMonthInput: String = YearMonth.now().toString(),
    val amountYuanInput: String = "",
    val payDayInput: String = "10",
    val validationError: UiText? = null,
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

private fun IncomePlanDraftUi.toRepositoryDraftOrNull(): IncomePlanDraft? {
    if (intentMonth.isEmpty()) return null
    val cleanLabel = label.trim().takeIf(String::isNotEmpty) ?: return null
    val amount = parsedAmountCents() ?: return null
    val payDay = parsedPayDay() ?: return null
    val incomeMonth = when (frequency) {
        IncomeFrequency.MONTHLY -> null
        IncomeFrequency.ONE_TIME -> parsedIncomeMonth() ?: return null
    }
    return IncomePlanDraft(
        intentMonth = intentMonth,
        homeCurrencyCode = homeCurrency?.storageKey ?: return null,
        label = cleanLabel,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amount,
        payDay = payDay,
    )
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

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    activeBinding = access?.binding
                    activeCanModify = access?.canModify ?: false
                    bindingGeneration += 1
                    _state.value = IncomePlanUiState(
                        canModify = access?.canModify ?: false,
                    )
                    queueJob?.cancel()
                    if (access != null) {
                        queueJob = viewModelScope.launch {
                            var completed = emptySet<Long>()
                            repository.observeEdits(access.binding).collect { rows ->
                                if (activeBinding != access.binding) return@collect
                                val done = rows.filter { it.row.status == PendingMutationStatus.Done }.map { it.row.id }.toSet()
                                _state.update { it.copy(pendingEdits = rows.filter { row -> row.row.status != PendingMutationStatus.Done }) }
                                if ((done - completed).isNotEmpty()) { onDataChanged(); refresh() }
                                completed = done
                            }
                        }
                        refresh()
                    }
                }
        }
    }

    fun refresh() {
        val expectedBinding = activeBinding ?: return
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
            val nextState = active.fold(
                onSuccess = { listing ->
                    val archivedError = archived.exceptionOrNull()?.toUiText(R.string.income_plan_archived_load_failed)
                    _state.value.copy(
                        isLoading = false,
                        loadState = IncomePlanLoadState.Loaded,
                        canModify = activeCanModify,
                        activePlans = listing.plans,
                        archivedPlans = archived.getOrDefault(emptyList()),
                        scheduledAmountCents = listing.scheduledAmountCents,
                        forecastMonth = listing.month,
                        forecastCurrencyCode = listing.homeCurrencyCode,
                        missingCurrencyCodes = listing.missingCurrencyCodes,
                        addDraft = _state.value.addDraft.let { draft ->
                            draft.copy(intentMonth = draft.intentMonth.ifEmpty { listing.month },
                                incomeMonthInput = draft.incomeMonthInput.ifEmpty { listing.month },
                                homeCurrency = draft.homeCurrency ?: CurrencyCode.fromStorageKeyOrNull(listing.homeCurrencyCode))
                        },
                        currentMonthSummary = IncomePlanMonthSummary(listing.effectivePlanCount, listing.expectedAmountCents),
                        error = archivedError,
                    )
                },
                onFailure = { err ->
                    _state.value.copy(
                        isLoading = false,
                        loadState = IncomePlanLoadState.Failed,
                        error = err.toUiText(R.string.income_plan_load_failed),
                    )
                },
            )
            if (binding == bindingGeneration && refresh == refreshGeneration) {
                _state.value = nextState
            }
        }
    }

    fun updateDraftSource(value: IncomeSourceType) {
        _state.update { it.copy(addDraft = it.addDraft.copy(sourceType = value)) }
    }

    fun updateDraftFrequency(value: IncomeFrequency) {
        _state.update {
            it.copy(addDraft = it.addDraft.copy(frequency = value, validationError = null))
        }
    }

    fun updateDraftField(field: IncomePlanDraftField, value: String) {
        _state.update { state ->
            val draft = state.addDraft
            val nextDraft = when (field) {
                IncomePlanDraftField.Label -> draft.copy(label = value)
                IncomePlanDraftField.IncomeMonth -> draft.copy(incomeMonthInput = value)
                IncomePlanDraftField.Amount -> {
                    // R14-2：币种已注入时即时报解析失败（JPY 下输 "12.50" 不再静默 isValid=false）。
                    val parseFailed = draft.homeCurrency != null && value.isNotBlank() &&
                        parseAmountCents(value, draft.homeCurrency) == null
                    return@update state.copy(
                        addDraft = draft.copy(
                            amountYuanInput = value,
                            validationError = if (parseFailed) UiText.res(R.string.expense_edit_amount_invalid) else null,
                        ),
                    )
                }
                IncomePlanDraftField.PayDay -> draft.copy(payDayInput = value)
            }
            state.copy(addDraft = nextDraft.copy(validationError = null))
        }
    }

    fun shiftDraftIncomeMonth(deltaMonths: Long) {
        _state.update { state ->
            val current = runCatching {
                YearMonth.parse(state.addDraft.incomeMonthInput.trim())
            }.getOrDefault(YearMonth.now())
            state.copy(
                addDraft = state.addDraft.copy(
                    incomeMonthInput = current.plusMonths(deltaMonths).toString(),
                    validationError = null,
                ),
            )
        }
    }

    fun resetDraft() {
        _state.update { it.copy(addDraft = IncomePlanDraftUi(intentMonth = it.forecastMonth.orEmpty(),
            incomeMonthInput = it.forecastMonth.orEmpty(), homeCurrency = CurrencyCode.fromStorageKeyOrNull(it.forecastCurrencyCode)),
            isSubmitting = false, addSucceeded = false) }
    }

    fun submitDraft() {
        val expectedBinding = activeBinding ?: return
        if (_state.value.addDraft.homeCurrency == null) {
            // R12-D：币种未确认禁写（不落 CNY 兜底）。
            _state.update {
                it.copy(
                    addDraft = it.addDraft.copy(
                        validationError = UiText.res(R.string.currency_unconfirmed_write_blocked),
                    ),
                )
            }
            return
        }
        val draft = _state.value.addDraft.toRepositoryDraftOrNull()
        if (draft == null) {
            _state.update {
                it.copy(
                    addDraft = it.addDraft.copy(
                        validationError = UiText.res(R.string.income_plan_validation_error),
                    ),
                )
            }
            return
        }
        val binding = bindingGeneration
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.create(expectedBinding, draft)
            if (binding != bindingGeneration) return@launch
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = IncomePlanDraftUi(intentMonth = it.forecastMonth.orEmpty(),
                                incomeMonthInput = it.forecastMonth.orEmpty(), homeCurrency = it.addDraft.homeCurrency),
                            flashMessage = UiText.res(R.string.income_plan_added),
                            addSucceeded = true,
                        )
                    }
                    onDataChanged()
                    refresh()
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = it.addDraft.copy(
                                validationError = err.toUiText(R.string.income_plan_add_failed),
                            ),
                        )
                    }
                },
            )
        }
    }

    fun recoverEdit(pending: PendingIncomePlanEdit, drop: Boolean) {
        val binding = activeBinding ?: return
        if (pending !in _state.value.pendingEdits) return
        viewModelScope.launch {
            repository.recoverEdit(binding, pending, drop).onFailure { error ->
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
            handleSimpleResult(
                result,
                success = UiText.res(R.string.income_plan_restored),
                binding = binding,
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    private fun handleSimpleResult(
        result: Result<IncomePlan>,
        success: UiText,
        binding: Int,
    ) {
        if (binding != bindingGeneration) return
        result.fold(
            onSuccess = {
                _state.update { it.copy(flashMessage = success) }
                onDataChanged()
                refresh()
            },
            onFailure = { err ->
                _state.update { it.copy(error = err.toUiText(R.string.error_generic)) }
            },
        )
    }
}
