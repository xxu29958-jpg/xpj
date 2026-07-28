package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import java.time.YearMonth
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CreateSpendingGoalUiState(
    val canModify: Boolean = true,
    val name: String = "",
    val month: String = YearMonth.now().toString(),
    val targetAmountInput: String = "",
    val category: String = "",
    val isSubmitting: Boolean = false,
    val formError: UiText? = null,
    val createdPublicId: String? = null,
    /**
     * 账本币种（R12-D）：Goal 不带币种字段（服务端按账本 home 聚合），新建流上没有 record 可
     * 提供 homeCurrencyCode —— 取列表信封的安装级 capability（PR#255 R6 同源信封）严格解析；
     * null = 未确认/未知 → 禁写（不落 CNY 兜底，JPY/KRW 安装下 "1200" 会被放大成 120000）。
     */
    val ledgerCurrency: CurrencyCode? = null,
) {
    val canSubmit: Boolean
        get() = canModify &&
            !isSubmitting &&
            ledgerCurrency != null &&
            name.trim().isNotEmpty() &&
            (ledgerCurrency.let { parseAmountCents(targetAmountInput, it)?.let { a -> a > 0L } == true })
}

class CreateSpendingGoalViewModel(
    private val reports: ReportsActions,
    private val debts: DebtActions,
) : ViewModel() {
    private val _state = MutableStateFlow(CreateSpendingGoalUiState(canModify = reports.canModifyLedger()))
    val state: StateFlow<CreateSpendingGoalUiState> = _state.asStateFlow()

    init {
        resolveLedgerCurrency()
    }

    fun reset(month: String = YearMonth.now().toString()) {
        _state.value = CreateSpendingGoalUiState(
            canModify = reports.canModifyLedger(),
            month = month.cleanGoalMonth(),
        )
        resolveLedgerCurrency()
    }

    /** R12-D：从列表信封的安装级 capability 解析账本币种（严格；未知 → null 禁写）。 */
    private fun resolveLedgerCurrency() {
        viewModelScope.launch {
            val code = debts.listDebts().getOrNull()?.ledgerHomeCurrencyCode
            _state.update { it.copy(ledgerCurrency = CurrencyCode.fromStorageKeyOrNull(code)) }
        }
    }

    fun updateName(value: String) {
        _state.update { it.copy(name = value, formError = null) }
    }

    fun updateTargetAmount(value: String) {
        _state.update { it.copy(targetAmountInput = value, formError = null) }
    }

    fun updateCategory(value: String) {
        _state.update { it.copy(category = value, formError = null) }
    }

    fun previousMonth() {
        shiftMonth(-1)
    }

    fun nextMonth() {
        shiftMonth(1)
    }

    fun submit() {
        val current = _state.value
        // R12-D：币种未确认禁写（不落 CNY 兜底）。
        val currency = current.ledgerCurrency
        if (currency == null) {
            _state.update { it.copy(formError = UiText.res(R.string.currency_unconfirmed_write_blocked)) }
            return
        }
        val amountCents = parseAmountCents(current.targetAmountInput, currency)
        if (current.name.trim().isBlank() || amountCents == null || amountCents <= 0L) {
            _state.update { it.copy(formError = UiText.res(R.string.spending_goal_create_validation)) }
            return
        }
        _state.update { it.copy(isSubmitting = true, formError = null) }
        viewModelScope.launch {
            reports.createGoal(
                GoalDraft(
                    name = current.name,
                    month = current.month,
                    targetAmountCents = amountCents,
                    category = current.category,
                ),
            ).fold(
                onSuccess = { goal ->
                    _state.update { it.copy(isSubmitting = false, createdPublicId = goal.publicId) }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            formError = err.toUiText(R.string.spending_goal_create_failed),
                        )
                    }
                },
            )
        }
    }

    fun consumeCreated() {
        _state.update { it.copy(createdPublicId = null) }
    }

    private fun shiftMonth(delta: Long) {
        _state.update {
            val next = runCatching { YearMonth.parse(it.month).plusMonths(delta) }
                .getOrDefault(YearMonth.now())
                .toString()
            it.copy(month = next, formError = null)
        }
    }
}

private fun String.cleanGoalMonth(): String =
    runCatching { YearMonth.parse(trim()).toString() }.getOrDefault(YearMonth.now().toString())
