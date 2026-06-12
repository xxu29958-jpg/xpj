package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.YearMonth

data class BudgetCategoryInput(
    val category: String = "",
    val amount: String = "",
)

data class BudgetFormState(
    val totalAmount: String = "",
    val rolloverAmount: String = "",
    val nonMonthlyAmount: String = "",
    val excludedCategories: String = "",
    val categoryRows: List<BudgetCategoryInput> = listOf(BudgetCategoryInput()),
)

data class BudgetUiState(
    val month: String = YearMonth.now().toString(),
    val loading: Boolean = false,
    val saving: Boolean = false,
    val message: UiText? = null,
    /**
     * 本月预算**加载失败**且无数据时的错误说明（区别于 [message]：后者还承载保存成功 /
     * 校验提示等）。仅当 [budget] 为空、非 [loading] 时由概况卡渲染为可重试错误态（审计 8.4）。
     */
    val loadError: UiText? = null,
    val canModify: Boolean = true,
    val budget: BudgetMonthly? = null,
    val form: BudgetFormState = BudgetFormState(),
)

class BudgetViewModel(
    private val repository: BudgetActions,
    initialMonth: String = YearMonth.now().toString(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        BudgetUiState(
            month = initialMonth,
            canModify = repository.canModifyLedger(),
        ),
    )
    val uiState: StateFlow<BudgetUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0

    init {
        observeLedgerChanges()
        refresh()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    requestGeneration += 1
                    _uiState.update {
                        it.copy(
                            loading = true,
                            saving = false,
                            budget = null,
                            form = BudgetFormState(),
                            message = null,
                            loadError = null,
                            canModify = repository.canModifyLedger(),
                        )
                    }
                    refresh()
                }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            val month = _uiState.value.month
            val generation = requestGeneration
            _uiState.update {
                it.copy(loading = true, message = null, loadError = null, canModify = repository.canModifyLedger())
            }
            repository.monthlyBudget(month)
                .onSuccess { budget ->
                    _uiState.update {
                        if (requestGeneration != generation || it.month != month) return@update it
                        it.copy(
                            loading = false,
                            budget = budget,
                            form = budget.toFormState(),
                            loadError = null,
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        if (requestGeneration != generation || it.month != month) return@update it
                        // Load failure with no budget → a retryable error state, not the
                        // permanent "正在读取预算。" loading copy (audit 8.4). Distinct from
                        // [message] which carries save-flow / validation feedback.
                        it.copy(
                            loading = false,
                            loadError = error.toUiText(R.string.budget_message_load_failed),
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
        }
    }

    fun previousMonth() {
        changeMonth(-1)
    }

    fun nextMonth() {
        changeMonth(1)
    }

    fun updateTotalAmount(value: String) {
        updateForm { it.copy(totalAmount = value) }
    }

    fun updateRolloverAmount(value: String) {
        updateForm { it.copy(rolloverAmount = value) }
    }

    fun updateNonMonthlyAmount(value: String) {
        updateForm { it.copy(nonMonthlyAmount = value) }
    }

    fun updateExcludedCategories(value: String) {
        updateForm { it.copy(excludedCategories = value) }
    }

    fun updateCategoryRow(index: Int, category: String, amount: String) {
        updateForm { form ->
            val rows = form.categoryRows.toMutableList()
            if (index !in rows.indices) return@updateForm form
            rows[index] = rows[index].copy(category = category, amount = amount)
            form.copy(categoryRows = rows)
        }
    }

    fun addCategoryRow() {
        updateForm { it.copy(categoryRows = it.categoryRows + BudgetCategoryInput()) }
    }

    fun removeCategoryRow(index: Int) {
        updateForm { form ->
            val rows = form.categoryRows.toMutableList()
            if (index !in rows.indices) return@updateForm form
            rows.removeAt(index)
            form.copy(categoryRows = rows.ifEmpty { listOf(BudgetCategoryInput()) })
        }
    }

    fun save() {
        if (!repository.canModifyLedger()) {
            _uiState.update { it.copy(canModify = false, message = UiText.res(R.string.common_readonly_ledger)) }
            return
        }
        val month = _uiState.value.month
        val generation = requestGeneration
        val update = parseBudgetUpdate(_uiState.value.form)
            .getOrElse { error ->
                val message = (error as? BudgetInputError)?.uiText
                    ?: error.toUiText(R.string.budget_message_content_invalid)
                _uiState.update { it.copy(message = message) }
                return
            }
        viewModelScope.launch {
            _uiState.update { it.copy(saving = true, message = null, canModify = repository.canModifyLedger()) }
            repository.saveMonthlyBudget(month, update)
                .onSuccess { budget ->
                    _uiState.update {
                        if (requestGeneration != generation || it.month != month) return@update it
                        it.copy(
                            saving = false,
                            budget = budget,
                            form = budget.toFormState(),
                            message = UiText.res(R.string.budget_message_saved),
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        if (requestGeneration != generation || it.month != month) return@update it
                        it.copy(
                            saving = false,
                            message = error.toUiText(R.string.budget_message_save_failed),
                            canModify = repository.canModifyLedger(),
                        )
                    }
                }
        }
    }

    private fun changeMonth(delta: Long) {
        val current = runCatching { YearMonth.parse(_uiState.value.month) }
            .getOrDefault(YearMonth.now())
        requestGeneration += 1
        _uiState.update {
            it.copy(
                month = current.plusMonths(delta).toString(),
                budget = null,
                form = BudgetFormState(),
                message = null,
                loadError = null,
            )
        }
        refresh()
    }

    private fun updateForm(transform: (BudgetFormState) -> BudgetFormState) {
        _uiState.update { it.copy(form = transform(it.form), message = null) }
    }
}

private fun BudgetMonthly.toFormState(): BudgetFormState {
    if (!configured) {
        return BudgetFormState()
    }
    return BudgetFormState(
        totalAmount = amountInput(totalAmountCents),
        rolloverAmount = amountInput(rolloverAmountCents),
        nonMonthlyAmount = amountInput(nonMonthlyAmountCents),
        excludedCategories = excludedCategories.joinToString("，"),
        categoryRows = categoryBudgets
            .map { BudgetCategoryInput(category = it.category, amount = amountInput(it.amountCents)) }
            .ifEmpty { listOf(BudgetCategoryInput()) },
    )
}

private class BudgetInputError(val uiText: UiText) : IllegalArgumentException()

private fun parseBudgetUpdate(form: BudgetFormState): Result<BudgetMonthlyUpdate> = runCatching {
    val total = parseRequiredCents(form.totalAmount, UiText.res(R.string.budget_validation_total_required))
    if (total <= 0L) throw BudgetInputError(UiText.res(R.string.budget_validation_total_positive))
    val rollover = parseOptionalCents(
        form.rolloverAmount,
        allowNegative = true,
        amountInvalid = UiText.res(R.string.budget_validation_rollover_amount_invalid),
        negative = UiText.res(R.string.budget_validation_rollover_negative),
    )
    val nonMonthly = parseOptionalCents(
        form.nonMonthlyAmount,
        allowNegative = false,
        amountInvalid = UiText.res(R.string.budget_validation_nonmonthly_amount_invalid),
        negative = UiText.res(R.string.budget_validation_nonmonthly_negative),
    )
    val rows = form.categoryRows.mapNotNull { row ->
        val category = row.category.trim()
        val amountText = row.amount.trim()
        if (category.isBlank() && amountText.isBlank()) return@mapNotNull null
        if (category.isBlank()) throw BudgetInputError(UiText.res(R.string.budget_validation_category_name_required))
        BudgetCategoryDraft(
            category = category,
            amountCents = parseRequiredCents(amountText, UiText.res(R.string.budget_validation_category_amount_required)).also {
                if (it < 0L) throw BudgetInputError(UiText.res(R.string.budget_validation_category_amount_negative))
            },
        )
    }
    BudgetMonthlyUpdate(
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

private fun parseRequiredCents(value: String, blankError: UiText): Long {
    val trimmed = value.trim()
    if (trimmed.isBlank()) throw BudgetInputError(blankError)
    return parseCents(trimmed) ?: throw BudgetInputError(UiText.res(R.string.budget_validation_amount_invalid))
}

private fun parseOptionalCents(
    value: String,
    allowNegative: Boolean,
    amountInvalid: UiText,
    negative: UiText,
): Long {
    val trimmed = value.trim()
    if (trimmed.isBlank()) return 0L
    val amount = parseCents(trimmed) ?: throw BudgetInputError(amountInvalid)
    if (!allowNegative && amount < 0L) throw BudgetInputError(negative)
    return amount
}

private fun parseCents(value: String): Long? {
    return runCatching {
        BigDecimal(value)
            .multiply(BigDecimal(100))
            .setScale(0, RoundingMode.HALF_UP)
            .longValueExact()
    }.getOrNull()
}

private fun amountInput(amountCents: Long): String {
    if (amountCents == 0L) return ""
    return BigDecimal(amountCents)
        .divide(BigDecimal(100), 2, RoundingMode.HALF_UP)
        .stripTrailingZeros()
        .toPlainString()
}
