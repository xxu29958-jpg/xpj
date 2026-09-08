package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.squareup.moshi.JsonClass
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingBudgetSave
import com.ticketbox.data.repository.toRequest
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.parseExactMoneyMinor
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.math.BigDecimal
import java.time.YearMonth

@JsonClass(generateAdapter = true)
data class BudgetCategoryInput(val category: String = "", val amount: String = "")

@JsonClass(generateAdapter = true)
data class BudgetFormState(
    val totalAmount: String = "",
    val rolloverAmount: String = "",
    val nonMonthlyAmount: String = "",
    val excludedCategories: String = "",
    val categoryRows: List<BudgetCategoryInput> = listOf(BudgetCategoryInput()),
    val homeCurrencyCode: String? = null,
    val expectedRowVersion: Long? = null,
)

data class BudgetUiState(
    val month: String = YearMonth.now().toString(),
    val loading: Boolean = false,
    val saving: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val loadError: UiText? = null,
    val canModify: Boolean = false,
    val budget: BudgetMonthly? = null,
    val form: BudgetFormState = BudgetFormState(),
    val formDirty: Boolean = false,
    val saves: List<PendingBudgetSave> = emptyList(),
) {
    val formCurrency: CurrencyCode? get() = CurrencyCode.fromStorageKeyOrNull(form.homeCurrencyCode)
    val hasPendingSave: Boolean get() = saves.any { it.row.status != PendingMutationStatus.Done }
}

class BudgetViewModel(
    private val repository: BudgetActions,
    initialMonth: String = YearMonth.now().toString(),
    private val onDataChanged: () -> Unit = {},
    private val savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    private val drafts = BudgetDraftStore(savedStateHandle)
    private val _uiState = MutableStateFlow(BudgetUiState(month = savedStateHandle["budget.month"] ?: initialMonth))
    val uiState: StateFlow<BudgetUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0
    private var refreshGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var savesJob: Job? = null
    private var observedSaves: List<PendingBudgetSave> = emptyList()

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess().distinctUntilChanged().collect { access ->
                if (activeBinding == access?.binding) {
                    _uiState.update { it.copy(canModify = access?.canModify == true) }
                } else {
                    activeBinding = access?.binding
                    requestGeneration += 1
                    savesJob?.cancel()
                    observedSaves = emptyList()
                    _uiState.value = BudgetUiState(month = _uiState.value.month, canModify = access?.canModify == true)
                    restoreDraft()
                    access?.let { observeSaves(it.binding); refresh() }
                }
            }
        }
    }

    private fun observeSaves(binding: LogicalSessionBinding) {
        savesJob = viewModelScope.launch {
            var previousDone: Set<Long>? = null
            repository.observeSaves(binding).collect { saves ->
                if (activeBinding != binding) return@collect
                observedSaves = saves
                val done = saves.filter { it.row.status == PendingMutationStatus.Done }
                val newlyDone = done.filter { previousDone != null && it.row.id !in previousDone.orEmpty() &&
                    it.intent?.month == _uiState.value.month }.maxByOrNull { it.row.id }
                previousDone = done.map { it.row.id }.toSet()
                updateObservedSaves(binding, newlyDone)
                if (newlyDone != null) { onDataChanged(); refresh() }
            }
        }
    }

    private fun updateObservedSaves(binding: LogicalSessionBinding, newlyDone: PendingBudgetSave?) {
        val state = _uiState.value
        val rows = observedSaves.forMonth(state.month)
        val transferred = rows.firstOrNull { state.formDirty && it.matches(state.form) }
        if (transferred != null) drafts.remove(binding, state.month, state.form)
        val dirty = state.formDirty && transferred == null
        val receipt = (newlyDone ?: transferred)?.receipt?.takeUnless { dirty }
        val pending = rows.firstOrNull { it.row.status != PendingMutationStatus.Done }
        _uiState.value = state.copy(saves = rows,
            form = receipt?.toFormState() ?: pending?.originalForm()?.takeUnless { dirty } ?: state.form,
            formDirty = dirty,
            message = if (receipt != null) UiText.res(R.string.budget_message_saved) else state.message,
            messageTone = if (receipt != null) MessageTone.Success else state.messageTone)
    }

    fun refresh() {
        if (_uiState.value.saving) return
        val binding = activeBinding ?: return
        val generation = requestGeneration
        val refresh = ++refreshGeneration
        val month = _uiState.value.month
        _uiState.update { it.copy(loading = true, loadError = null) }
        viewModelScope.launch {
            repository.monthlyBudget(binding, month).fold(onSuccess = { budget ->
                _uiState.update { state ->
                    if (!isCurrent(generation, month) || refresh != refreshGeneration) state else state.copy(
                        loading = false, budget = budget, loadError = null,
                        form = if (!state.formDirty && !state.hasPendingSave) budget.toFormState() else state.form)
                }
            }, onFailure = { error ->
                _uiState.update { state ->
                    if (!isCurrent(generation, month) || refresh != refreshGeneration) state else state.copy(
                        loading = false, loadError = error.toUiText(if (state.budget == null)
                            R.string.budget_message_load_failed else R.string.budget_message_refresh_failed_with_data))
                }
            })
        }
    }

    fun previousMonth() = changeMonth(-1)
    fun nextMonth() = changeMonth(1)
    fun updateTotalAmount(value: String) = updateForm { it.copy(totalAmount = value) }
    fun updateRolloverAmount(value: String) = updateForm { it.copy(rolloverAmount = value) }
    fun updateNonMonthlyAmount(value: String) = updateForm { it.copy(nonMonthlyAmount = value) }
    fun updateExcludedCategories(value: String) = updateForm { it.copy(excludedCategories = value) }
    fun updateCategoryRow(index: Int, category: String, amount: String) = updateForm { form ->
        form.copy(categoryRows = form.categoryRows.mapIndexed { rowIndex, row ->
            if (rowIndex == index) BudgetCategoryInput(category, amount) else row })
    }
    fun addCategoryRow() = updateForm { it.copy(categoryRows = it.categoryRows + BudgetCategoryInput()) }
    fun removeCategoryRow(index: Int) = updateForm { form ->
        form.copy(categoryRows = form.categoryRows.filterIndexed { rowIndex, _ -> rowIndex != index }
            .ifEmpty { listOf(BudgetCategoryInput()) })
    }

    fun save() {
        val state = _uiState.value
        if (state.saving || state.hasPendingSave) return
        val binding = activeBinding ?: return
        if (!state.canModify || !repository.canModifyLedger()) {
            _uiState.update { it.copy(canModify = false, message = UiText.res(R.string.common_readonly_ledger), messageTone = MessageTone.Danger) }
            return
        }
        val currency = state.formCurrency
        if (currency == null) {
            _uiState.update { it.copy(message = UiText.res(R.string.currency_unconfirmed_write_blocked), messageTone = MessageTone.Danger) }
            return
        }
        val update = parseBudgetUpdate(state.form, currency).getOrElse { error ->
            _uiState.update { it.copy(message = (error as? BudgetInputError)?.uiText
                ?: error.toUiText(R.string.budget_message_content_invalid), messageTone = MessageTone.Danger) }
            return
        }
        val generation = requestGeneration
        refreshGeneration += 1
        _uiState.update { it.copy(saving = true, loading = false, message = null) }
        viewModelScope.launch {
            val result = repository.enqueueSave(binding, state.month, update)
            result.onSuccess { drafts.remove(binding, state.month, state.form) }
            if (!isCurrent(generation, state.month)) return@launch
            showEnqueueResult(result)
        }
    }

    private fun showEnqueueResult(result: Result<Long>) {
        result.fold(onSuccess = { id ->
            val confirmed = observedSaves.any { it.row.id == id && it.row.status == PendingMutationStatus.Done }
            _uiState.update { it.copy(saving = false, formDirty = false,
                message = UiText.res(if (confirmed) R.string.budget_message_saved else R.string.budget_message_queued),
                messageTone = if (confirmed) MessageTone.Success else MessageTone.Info) }
        }, onFailure = { error ->
            _uiState.update { it.copy(saving = false, message = error.toUiText(R.string.budget_message_save_failed), messageTone = MessageTone.Danger) }
        })
    }

    fun recoverSave(pending: PendingBudgetSave, drop: Boolean) {
        val binding = activeBinding ?: return
        val generation = requestGeneration
        val month = _uiState.value.month
        viewModelScope.launch {
            val result = repository.recoverSave(binding, pending, drop)
            if (!isCurrent(generation, month)) return@launch
            result.onSuccess { if (drop) { drafts.remove(binding, month); _uiState.update { it.copy(formDirty = false) }; refresh() } }
                .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.budget_message_save_failed), messageTone = MessageTone.Danger) } }
        }
    }

    private fun isCurrent(generation: Int, month: String): Boolean = requestGeneration == generation && _uiState.value.month == month

    private fun changeMonth(delta: Long) {
        if (_uiState.value.saving) return
        val month = YearMonth.parse(_uiState.value.month).plusMonths(delta).toString()
        savedStateHandle["budget.month"] = month
        requestGeneration += 1
        _uiState.update { BudgetUiState(month = month, canModify = it.canModify, saves = observedSaves.forMonth(month)) }
        restoreDraft()
        refresh()
    }

    private fun restoreDraft() {
        val binding = activeBinding ?: return
        val form = drafts.read(binding, _uiState.value.month)
        _uiState.update { it.copy(form = form ?: it.saves.firstOrNull {
            save -> save.row.status != PendingMutationStatus.Done }?.originalForm() ?: BudgetFormState(), formDirty = form != null) }
    }

    private fun updateForm(transform: (BudgetFormState) -> BudgetFormState) {
        _uiState.update { if (it.saving || it.hasPendingSave) it else it.copy(form = transform(it.form),
            formDirty = true, message = null, messageTone = MessageTone.Neutral) }
        val state = _uiState.value
        if (state.formDirty) activeBinding?.let { drafts.write(it, state.month, state.form) }
    }
}

private fun List<PendingBudgetSave>.forMonth(month: String): List<PendingBudgetSave> = filter {
    it.row.targetId == "monthly_budget:$month"
}.let { rows -> rows.filter { it.row.status != PendingMutationStatus.Done } +
    listOfNotNull(rows.filter { it.row.status == PendingMutationStatus.Done }.maxByOrNull { it.row.id }) }

private fun PendingBudgetSave.matches(form: BudgetFormState): Boolean {
    val payload = intent ?: return false
    val currency = CurrencyCode.fromStorageKeyOrNull(form.homeCurrencyCode) ?: return false
    val request = parseBudgetUpdate(form, currency).getOrNull()?.toRequest() ?: return false
    return row.expectedRowVersion == (form.expectedRowVersion ?: 0L) &&
        payload.request == request.copy(expectedRowVersion = null)
}

private fun PendingBudgetSave.originalForm(): BudgetFormState? {
    val request = intent?.request ?: return null
    val currency = CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode) ?: return null
    return BudgetFormState(
        totalAmount = amountInput(request.totalAmountCents, currency),
        rolloverAmount = amountInput(request.rolloverAmountCents, currency),
        nonMonthlyAmount = amountInput(request.nonMonthlyAmountCents, currency),
        excludedCategories = request.excludedCategories.joinToString("，"),
        categoryRows = request.categoryBudgets.map { BudgetCategoryInput(it.category, amountInput(it.amountCents, currency)) }
            .ifEmpty { listOf(BudgetCategoryInput()) },
        homeCurrencyCode = request.homeCurrencyCode, expectedRowVersion = row.expectedRowVersion.takeIf { it > 0 },
    )
}

private fun BudgetMonthly.toFormState(): BudgetFormState {
    val currency = CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)
        ?: return BudgetFormState(homeCurrencyCode = homeCurrencyCode, expectedRowVersion = rowVersion)
    if (!configured) return BudgetFormState(homeCurrencyCode = homeCurrencyCode, expectedRowVersion = rowVersion)
    return BudgetFormState(
        totalAmount = amountInput(totalAmountCents, currency),
        rolloverAmount = amountInput(rolloverAmountCents, currency),
        nonMonthlyAmount = amountInput(nonMonthlyAmountCents, currency),
        excludedCategories = excludedCategories.joinToString("，"),
        categoryRows = categoryBudgets.map { BudgetCategoryInput(it.category, amountInput(it.amountCents, currency)) }
            .ifEmpty { listOf(BudgetCategoryInput()) },
        homeCurrencyCode = homeCurrencyCode, expectedRowVersion = rowVersion)
}

private class BudgetInputError(val uiText: UiText) : IllegalArgumentException()

private fun parseBudgetUpdate(form: BudgetFormState, currency: CurrencyCode): Result<BudgetMonthlyUpdate> = runCatching {
    val total = parseRequiredCents(form.totalAmount, UiText.res(R.string.budget_validation_total_required), currency)
    if (total <= 0L) throw BudgetInputError(UiText.res(R.string.budget_validation_total_positive))
    val rollover = parseOptionalCents(
        form.rolloverAmount,
        allowNegative = true,
        amountInvalid = UiText.res(R.string.budget_validation_rollover_amount_invalid),
        negative = UiText.res(R.string.budget_validation_rollover_negative),
        currency = currency,
    )
    val nonMonthly = parseOptionalCents(
        form.nonMonthlyAmount,
        allowNegative = false,
        amountInvalid = UiText.res(R.string.budget_validation_nonmonthly_amount_invalid),
        negative = UiText.res(R.string.budget_validation_nonmonthly_negative),
        currency = currency,
    )
    val rows = form.categoryRows.mapNotNull { row ->
        val category = row.category.trim()
        val amountText = row.amount.trim()
        if (category.isBlank() && amountText.isBlank()) return@mapNotNull null
        if (category.isBlank()) throw BudgetInputError(UiText.res(R.string.budget_validation_category_name_required))
        BudgetCategoryDraft(
            category = category,
            amountCents = parseRequiredCents(amountText, UiText.res(R.string.budget_validation_category_amount_required), currency).also {
                if (it < 0L) throw BudgetInputError(UiText.res(R.string.budget_validation_category_amount_negative))
            },
        )
    }
    BudgetMonthlyUpdate(
        homeCurrencyCode = currency.storageKey,
        expectedRowVersion = form.expectedRowVersion,
        totalAmountCents = total,
        nonMonthlyAmountCents = nonMonthly,
        rolloverAmountCents = rollover,
        excludedCategories = splitCategories(form.excludedCategories),
        categoryBudgets = rows,
    )
}

private fun splitCategories(value: String): List<String> {
    val seen = linkedSetOf<String>()
    Regex("[,，;；\\n]+")
        .split(value)
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .forEach { seen += it }
    return seen.toList()
}

private fun parseRequiredCents(value: String, blankError: UiText, currency: CurrencyCode): Long {
    val trimmed = value.trim()
    if (trimmed.isBlank()) throw BudgetInputError(blankError)
    return parseCents(trimmed, currency) ?: throw BudgetInputError(UiText.res(R.string.budget_validation_amount_invalid))
}

private fun parseOptionalCents(
    value: String,
    allowNegative: Boolean,
    amountInvalid: UiText,
    negative: UiText,
    currency: CurrencyCode,
): Long {
    val trimmed = value.trim()
    if (trimmed.isBlank()) return 0L
    val amount = parseCents(trimmed, currency) ?: throw BudgetInputError(amountInvalid)
    if (!allowNegative && amount < 0L) throw BudgetInputError(negative)
    return amount
}

// R13-7：按账本币种 exponent 精确解析（JPY/KRW 零小数不 ×100）。多余的非零
// 精度一律拒绝，等值尾零（如 CNY "1.230"）可接受，不做 HALF_UP；负值仅 rollover 可用。
private fun parseCents(
    value: String,
    currency: CurrencyCode,
): Long? = parseExactMoneyMinor(value, currency, allowNegative = true)

private fun amountInput(amountCents: Long, currency: CurrencyCode): String {
    if (amountCents == 0L) return ""
    return BigDecimal(amountCents)
        .movePointLeft(currency.minorUnitDigits)
        .stripTrailingZeros()
        .toPlainString()
}
