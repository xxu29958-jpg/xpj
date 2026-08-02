package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.parseExactMoneyMinor
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.math.BigDecimal
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
    val messageTone: MessageTone = MessageTone.Neutral,
    /**
     * 本月预算读取 / 刷新失败说明（区别于 [message]：后者还承载保存成功 /
     * 校验提示等）。无 [budget] 时由概况卡渲染为可重试错误态；已有 [budget] 时保留旧数据并以内联
     * 提示说明刷新失败。
     */
    val loadError: UiText? = null,
    val canModify: Boolean = true,
    val budget: BudgetMonthly? = null,
    val form: BudgetFormState = BudgetFormState(),
    /** 账本币种（R13-7）：VM 由列表信封 capability 注入；null=未确认 → 禁写（不落 CNY
     *  兜底 ×100）。回填显示在未确认时落 display-home 兜底（save 由本字段禁写）。 */
    val ledgerCurrency: CurrencyCode? = null,
)

class BudgetViewModel(
    private val repository: BudgetActions,
    private val debts: DebtActions,
    initialMonth: String = YearMonth.now().toString(),
    private val onDataChanged: () -> Unit = {},
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        BudgetUiState(
            month = initialMonth,
            canModify = false,
        ),
    )
    val uiState: StateFlow<BudgetUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0
    private var refreshGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var activeCanModify = false

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    activeBinding = access?.binding
                    activeCanModify = access?.canModify ?: false
                    requestGeneration += 1
                    _uiState.update {
                        it.copy(
                            loading = access != null,
                            saving = false,
                            budget = null,
                            form = BudgetFormState(),
                            message = null,
                            messageTone = MessageTone.Neutral,
                            loadError = null,
                            canModify = access?.canModify ?: false,
                            // R15a-1：账本切换清旧币种重解析 —— 旧币种不得在解析窗口内
                            // 参与回填/放行（R13-7 竞态变体）。
                            ledgerCurrency = null,
                        )
                    }
                    if (access != null) {
                        // R15a-1+R15a-2：同协程串行 —— 先解析币种（代际守卫 last-writer-wins），
                        // 后 refresh/回填；离线 null 时读面仍刷新，表单空 + 禁写，不按兜底
                        // 币种缩放回填（R13-7 回填×save 分裂竞态的修复）。
                        refreshLedgerCurrency()
                        refresh()
                    }
                }
        }
    }

    private var currencyResolutionGeneration = 0L

    /**
     * （重新）解析账本币种（R15a-2，信封 capability 严格解析，未知 → null 禁写）。
     * 代际守卫：并发解析 last-writer-wins（快速切账本旧结果不得后于新结果落定）。
     * 币种到达且表单仍处未触碰默认态（解析窗口内 refresh 落了空表单）时按确认币种重回填。
     */
    private suspend fun refreshLedgerCurrency() {
        val generation = ++currencyResolutionGeneration
        val resolved = CurrencyCode.fromStorageKeyOrNull(debts.listDebts().getOrNull()?.ledgerHomeCurrencyCode)
        _uiState.update { state ->
            if (generation != currencyResolutionGeneration) return@update state
            val budget = state.budget
            val rebackfill = resolved != null && budget != null && state.form == BudgetFormState()
            state.copy(
                ledgerCurrency = resolved,
                form = if (rebackfill) budget.toFormState(resolved) else state.form,
            )
        }
    }

    fun refresh() {
        if (_uiState.value.saving) return
        val binding = activeBinding ?: return
        val generation = requestGeneration
        val refresh = ++refreshGeneration
        viewModelScope.launch {
            val month = _uiState.value.month
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    loadError = null,
                    canModify = activeCanModify,
                )
            }
            repository.monthlyBudget(binding, month)
                .onSuccess { budget ->
                    _uiState.update {
                        if (!isCurrentRefresh(generation, refresh, month, it.month)) return@update it
                        it.copy(
                            loading = false,
                            budget = budget,
                            // R15a-1：币种已确认才回填（init 已串行解析；null=离线/未知 →
                            // 空表单 + 禁写，不按兜底币种缩放撒谎）。
                            form = it.ledgerCurrency?.let { currency -> budget.toFormState(currency) }
                                ?: BudgetFormState(),
                            loadError = null,
                            canModify = activeCanModify,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update {
                        if (!isCurrentRefresh(generation, refresh, month, it.month)) return@update it
                        // Initial failure → a retryable error state; refresh failure with
                        // readable data keeps the previous budget and surfaces a stale notice.
                        val fallback = if (it.budget == null) {
                            R.string.budget_message_load_failed
                        } else {
                            R.string.budget_message_refresh_failed_with_data
                        }
                        it.copy(
                            loading = false,
                            loadError = error.toUiText(fallback),
                            canModify = activeCanModify,
                        )
                    }
                }
        }
    }

    private fun isCurrentRefresh(
        generation: Int,
        refresh: Int,
        requestedMonth: String,
        currentMonth: String,
    ): Boolean = requestGeneration == generation &&
        refreshGeneration == refresh &&
        requestedMonth == currentMonth

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
        if (_uiState.value.saving) return
        val binding = activeBinding ?: return
        if (!repository.canModifyLedger()) {
            _uiState.update {
                it.copy(
                    canModify = false,
                    message = UiText.res(R.string.common_readonly_ledger),
                    messageTone = MessageTone.Danger,
                )
            }
            return
        }
        // 写按点按瞬间快照构建（binding + form + 已确认币种）：切账本事件在队列中先于
        // 保存协程处理时，也不得拿新账本的状态写旧表单（binding 竞态钉合同）。
        val month = _uiState.value.month
        val generation = requestGeneration
        val formSnapshot = _uiState.value.form
        val currencySnapshot = _uiState.value.ledgerCurrency
        // saving 同步置位：refresh/重复 save 从点按瞬间即串行（串行化钉合同）。
        _uiState.update { it.withSaveStarted(activeCanModify) }
        viewModelScope.launch {
            performSave(binding, month, generation, formSnapshot, currencySnapshot)
        }
    }

    private suspend fun performSave(
        binding: LogicalSessionBinding,
        month: String,
        generation: Int,
        formSnapshot: BudgetFormState,
        currencySnapshot: CurrencyCode?,
    ) {
        // R15a-2：币种未确认时先重解析再裁决 —— 离线冷启动的一次性门闩解除（网络恢复
        // 后写尝试自带重解析，不再会话级锁死）；R13-7 禁写口径不变（不落 CNY 兜底 ×100）。
        val currency = currencySnapshot ?: run {
            refreshLedgerCurrency()
            _uiState.value.ledgerCurrency
        }
        if (currency == null) {
            _uiState.update {
                it.copy(
                    saving = false,
                    message = UiText.res(R.string.currency_unconfirmed_write_blocked),
                    messageTone = MessageTone.Danger,
                )
            }
            return
        }
        // 快照在场路径坚持点按瞬间表单（binding 竞态钉合同）；快照缺失的恢复路径
        // （R15a-2）以重解析后的当前表单为准 —— 未触碰表单已按确认币种重回填。
        val formForWrite = if (currencySnapshot != null) formSnapshot else _uiState.value.form
        val update = parseBudgetUpdate(formForWrite, currency)
            .getOrElse { error ->
                val message = (error as? BudgetInputError)?.uiText
                    ?: error.toUiText(R.string.budget_message_content_invalid)
                _uiState.update { it.copy(saving = false, message = message, messageTone = MessageTone.Danger) }
                return
            }
        refreshGeneration += 1
        repository.saveMonthlyBudget(binding, month, update)
            .onSuccess { budget ->
                if (requestGeneration != generation ||
                    activeBinding != binding ||
                    _uiState.value.month != month
                ) {
                    return@onSuccess
                }
                _uiState.update { it.withSavedBudget(budget, activeCanModify) }
                onDataChanged()
            }
            .onFailure { error ->
                _uiState.update {
                    if (requestGeneration != generation ||
                        activeBinding != binding ||
                        it.month != month
                    ) {
                        return@update it
                    }
                    it.withSaveFailure(error, activeCanModify)
                }
            }
    }

    private fun changeMonth(delta: Long) {
        if (_uiState.value.saving) return
        val current = runCatching { YearMonth.parse(_uiState.value.month) }
            .getOrDefault(YearMonth.now())
        requestGeneration += 1
        _uiState.update {
            it.copy(
                month = current.plusMonths(delta).toString(),
                budget = null,
                form = BudgetFormState(),
                message = null,
                messageTone = MessageTone.Neutral,
                loadError = null,
            )
        }
        refresh()
    }

    private fun updateForm(transform: (BudgetFormState) -> BudgetFormState) {
        _uiState.update { it.copy(form = transform(it.form), message = null, messageTone = MessageTone.Neutral) }
    }
}

private fun BudgetUiState.withSaveStarted(canModify: Boolean): BudgetUiState = copy(
    loading = false,
    saving = true,
    message = null,
    messageTone = MessageTone.Neutral,
    canModify = canModify,
)

private fun BudgetUiState.withSavedBudget(
    budget: BudgetMonthly,
    canModify: Boolean,
): BudgetUiState = copy(
    loading = false,
    saving = false,
    budget = budget,
    // 保存成功重回填：save 门已保证币种非 null（R15a-1 同口径，null 时保留当前表单不撒谎）。
    form = ledgerCurrency?.let { budget.toFormState(it) } ?: form,
    message = UiText.res(R.string.budget_message_saved),
    messageTone = MessageTone.Success,
    loadError = null,
    canModify = canModify,
)

private fun BudgetUiState.withSaveFailure(
    error: Throwable,
    canModify: Boolean,
): BudgetUiState = copy(
    loading = false,
    saving = false,
    message = error.toUiText(R.string.budget_message_save_failed),
    messageTone = MessageTone.Danger,
    canModify = canModify,
)

private fun BudgetMonthly.toFormState(currency: CurrencyCode): BudgetFormState {
    if (!configured) {
        return BudgetFormState()
    }
    return BudgetFormState(
        totalAmount = amountInput(totalAmountCents, currency),
        rolloverAmount = amountInput(rolloverAmountCents, currency),
        nonMonthlyAmount = amountInput(nonMonthlyAmountCents, currency),
        excludedCategories = excludedCategories.joinToString("，"),
        categoryRows = categoryBudgets
            .map { BudgetCategoryInput(category = it.category, amount = amountInput(it.amountCents, currency)) }
            .ifEmpty { listOf(BudgetCategoryInput()) },
    )
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
