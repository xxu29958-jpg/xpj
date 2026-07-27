package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.LogicalSessionBinding
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
    val totalActiveAmountCents: Long = 0L,
    val currentMonthSummary: IncomePlanMonthSummary = IncomePlanMonthSummary(),
    val error: UiText? = null,
    val addDraft: IncomePlanDraftUi = IncomePlanDraftUi(),
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

/** 计划域概览用的本月收入汇总（218-B1 自 #218 摘取；完整收入计划重构属后续 slice）。 */
data class IncomePlanMonthSummary(
    val effectivePlanCount: Int = 0,
    val expectedAmountCents: Long = 0L,
    val historicalRecordCount: Int = 0,
)

private fun incomePlanMonthSummary(
    plans: List<IncomePlan>,
    currentMonth: YearMonth,
): IncomePlanMonthSummary {
    val currentMonthLabel = currentMonth.toString()
    val effectivePlans = plans.filter { plan ->
        plan.frequency == IncomeFrequency.MONTHLY || plan.incomeMonth == currentMonthLabel
    }
    val historicalRecordCount = plans.count { plan ->
        val incomeMonth = plan.incomeMonth?.let { value ->
            runCatching { YearMonth.parse(value) }.getOrNull()
        }
        plan.frequency == IncomeFrequency.ONE_TIME && incomeMonth?.isBefore(currentMonth) == true
    }
    return IncomePlanMonthSummary(
        effectivePlanCount = effectivePlans.size,
        expectedAmountCents = effectivePlans.sumOf(IncomePlan::amountCents),
        historicalRecordCount = historicalRecordCount,
    )
}

data class IncomePlanDraftUi(
    val label: String = "",
    val sourceType: IncomeSourceType = IncomeSourceType.SALARY,
    val frequency: IncomeFrequency = IncomeFrequency.ONE_TIME,
    val incomeMonthInput: String = YearMonth.now().toString(),
    val amountYuanInput: String = "",
    val payDayInput: String = "10",
    val validationError: UiText? = null,
) {
    val isValid: Boolean
        get() = label.trim().isNotEmpty() &&
            parsedAmountCents() != null &&
            parsedPayDay() != null &&
            (frequency == IncomeFrequency.MONTHLY || parsedIncomeMonth() != null)

    // 元→分走共享 BigDecimal 解析器（§3 禁 Double 存金额）。允许 0、拒负：极小负额（如 -0.004）在分空间
    // HALF_UP 会舍入到 0，故先按元符号拒负，保持旧「负数无效」语义、不静默当成 0 元计划。
    fun parsedAmountCents(): Long? {
        if (amountYuanInput.trim().startsWith('-')) return null
        return parseAmountCents(amountYuanInput)?.takeIf { it >= 0 }
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
    val cleanLabel = label.trim().takeIf(String::isNotEmpty) ?: return null
    val amount = parsedAmountCents() ?: return null
    val payDay = parsedPayDay() ?: return null
    val incomeMonth = when (frequency) {
        IncomeFrequency.MONTHLY -> null
        IncomeFrequency.ONE_TIME -> parsedIncomeMonth() ?: return null
    }
    return IncomePlanDraft(
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
                    if (access != null) refresh()
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
                        totalActiveAmountCents = listing.totalActiveAmountCents,
                        currentMonthSummary = incomePlanMonthSummary(listing.plans, YearMonth.now()),
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
                IncomePlanDraftField.Amount -> draft.copy(amountYuanInput = value)
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
        _state.update { it.copy(addDraft = IncomePlanDraftUi(), isSubmitting = false, addSucceeded = false) }
    }

    fun submitDraft() {
        val expectedBinding = activeBinding ?: return
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
                            addDraft = IncomePlanDraftUi(),
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

    fun archive(publicId: String, expectedRowVersion: Long) {
        val expectedBinding = activeBinding ?: return
        val binding = bindingGeneration
        viewModelScope.launch {
            val result = repository.archive(expectedBinding, publicId, expectedRowVersion)
            handleSimpleResult(
                result,
                success = UiText.res(R.string.income_plan_archived),
                binding = binding,
            )
        }
    }

    fun restore(publicId: String, expectedRowVersion: Long) {
        val expectedBinding = activeBinding ?: return
        val binding = bindingGeneration
        viewModelScope.launch {
            val result = repository.restore(expectedBinding, publicId, expectedRowVersion)
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
