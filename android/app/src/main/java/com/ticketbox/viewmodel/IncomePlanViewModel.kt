package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.IncomePlanSaveOutcome
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.isValidPayDay
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.CoroutineScope
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
    val currentMonthSummary: IncomePlanMonthSummary = IncomePlanMonthSummary(),
    val error: UiText? = null,
    val addDraft: IncomePlanDraftUi = IncomePlanDraftUi(),
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    val flashTone: MessageTone = MessageTone.Success,
    val editingPlan: IncomePlan? = null,
    /**
     * 一次性信号：[submitDraft] 真正成功后置 true；底部抽屉屏只在它为 true 时关闭（关时调
     * [resetDraft] 一并清掉本信号 + 草稿，镜像 LedgerViewModel.manualCreateDone 的 ack 约定）。
     * failure 不置位 → 抽屉保留、表单错误可见（修「乐观关闭」：旧逻辑按本地 `addDraft.isValid`
     * 关闭、无视 create() 结果，后端失败时静默丢失）。
     */
    val addSucceeded: Boolean = false,
    /** One-shot acknowledgement used to close the editor only after PATCH was saved or queued. */
    val editSucceeded: Boolean = false,
)

/**
 * Shared month semantics for both Plan overview and Income records.
 * Recurring rows and one-time rows for this month are effective; expected amount ignores payday.
 * Past one-time rows remain readable records, but never become effective for the current month.
 */
data class IncomePlanMonthSummary(
    val effectivePlanCount: Int = 0,
    val expectedAmountCents: Long = 0L,
    val historicalRecordCount: Int = 0,
)

enum class IncomePlanLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

data class IncomePlanDraftUi(
    val label: String = "",
    val sourceType: IncomeSourceType = IncomeSourceType.SALARY,
    val frequency: IncomeFrequency = IncomeFrequency.ONE_TIME,
    val incomeMonthInput: String = YearMonth.now().toString(),
    val amountYuanInput: String = "",
    val payDayInput: String = "10",
    val validationError: UiText? = null,
    val homeCurrency: CurrencyCode = CurrencyCode.LegacyFallback,
) {
    val isValid: Boolean
        get() = label.trim().isNotEmpty() &&
            parsedAmountCents() != null &&
            parsedPayDay() != null &&
            (frequency == IncomeFrequency.MONTHLY || parsedIncomeMonth() != null)

    // Shared parser requires exact representability in the server home currency.
    // Income plans allow zero but reject every negative input; no rounding is performed.
    fun parsedAmountCents(): Long? {
        if (amountYuanInput.trim().startsWith('-')) return null
        return parseAmountCents(amountYuanInput, homeCurrency)?.takeIf { it >= 0 }
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

private data class ValidatedIncomePlanDraft(
    val label: String,
    val sourceType: IncomeSourceType,
    val frequency: IncomeFrequency,
    val incomeMonth: String?,
    val amountCents: Long,
    val payDay: Int,
) {
    fun asCreateDraft(): IncomePlanDraft = IncomePlanDraft(
        label = label,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amountCents,
        payDay = payDay,
    )

    fun asPatch(expectedRowVersion: Long): IncomePlanPatch = IncomePlanPatch(
        expectedRowVersion = expectedRowVersion,
        label = label,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = incomeMonth,
        amountCents = amountCents,
        payDay = payDay,
    )
}

class IncomePlanViewModel(
    private val repository: IncomePlanActions,
    private val currentMonthProvider: () -> YearMonth = YearMonth::now,
    private val onDataChanged: () -> Unit = {},
) : ViewModel() {

    private val _state = MutableStateFlow(
        IncomePlanUiState(
            canModify = repository.canModifyLedger(),
            addDraft = IncomePlanDraftUi(homeCurrency = repository.currentHomeCurrency),
        ),
    )
    val state: StateFlow<IncomePlanUiState> = _state.asStateFlow()
    private var loadGeneration = 0L
    private val submissionCoordinator = IncomePlanSubmissionCoordinator(
        repository = repository,
        state = _state,
        currentMonthProvider = currentMonthProvider,
        callbacks = IncomePlanSubmissionCallbacks(
            onDataChanged = onDataChanged,
            refresh = ::refresh,
        ),
    )

    init {
        refresh()
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    // Active-ledger changes are a hard presentation boundary. Clear every
                    // ledger-bound value before starting the replacement request so an old
                    // list, summary, draft, or success banner cannot survive into the new
                    // ledger while its response is in flight.
                    _state.value = IncomePlanUiState(
                        canModify = repository.canModifyLedger(),
                        addDraft = IncomePlanDraftUi(homeCurrency = repository.currentHomeCurrency),
                    )
                    refresh()
                }
        }
    }

    fun refresh() {
        val generation = ++loadGeneration
        _state.update {
            it.copy(
                isLoading = true,
                loadState = IncomePlanLoadState.Loading,
                canModify = repository.canModifyLedger(),
                error = null,
            )
        }
        viewModelScope.launch {
            val active = repository.listActive()
            val archived = repository.listIncluding(
                com.ticketbox.domain.model.IncomePlanStatus.ARCHIVED,
            )
            if (generation != loadGeneration) return@launch
            val nextState = active.fold(
                onSuccess = { listing ->
                    val archivedError = archived.exceptionOrNull()?.toUiText(R.string.income_plan_archived_load_failed)
                    _state.value.copy(
                        isLoading = false,
                        loadState = IncomePlanLoadState.Loaded,
                        canModify = repository.canModifyLedger(),
                        activePlans = listing.plans,
                        archivedPlans = archived.getOrDefault(emptyList()),
                        currentMonthSummary = incomePlanMonthSummary(
                            plans = listing.plans,
                            currentMonth = currentMonthProvider(),
                        ),
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
            if (generation == loadGeneration) {
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

    fun beginEdit(plan: IncomePlan): Boolean {
        val canModify = repository.canModifyLedger()
        if (!canModify) {
            _state.update {
                it.copy(
                    canModify = false,
                    error = UiText.res(R.string.common_readonly_ledger),
                )
            }
            return false
        }
        if (plan.status != IncomePlanStatus.ACTIVE) {
            _state.update {
                it.copy(error = UiText.res(R.string.income_plan_edit_archived_first))
            }
            return false
        }
        _state.update {
            it.copy(
                editingPlan = plan,
                addDraft = IncomePlanDraftUi(
                    label = plan.label,
                    sourceType = plan.sourceType,
                    frequency = plan.frequency,
                    incomeMonthInput = plan.incomeMonth ?: currentMonthProvider().toString(),
                    amountYuanInput = formatAmountInput(
                        plan.amountCents,
                        repository.currentHomeCurrency,
                    ),
                    payDayInput = plan.payDay.toString(),
                    homeCurrency = repository.currentHomeCurrency,
                ),
                error = null,
                addSucceeded = false,
                editSucceeded = false,
            )
        }
        return true
    }

    fun resetDraft() {
        _state.update {
            it.copy(
                addDraft = IncomePlanDraftUi(homeCurrency = repository.currentHomeCurrency),
                isSubmitting = false,
                addSucceeded = false,
                editSucceeded = false,
                editingPlan = null,
            )
        }
    }

    fun submitDraft() {
        submissionCoordinator.submit(viewModelScope)
    }

    fun setArchived(
        publicId: String,
        expectedRowVersion: Long,
        archived: Boolean,
    ) {
        viewModelScope.launch {
            val result = if (archived) {
                repository.archive(publicId, expectedRowVersion)
            } else {
                repository.restore(publicId, expectedRowVersion)
            }
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            flashMessage = UiText.res(
                                if (archived) R.string.income_plan_archived
                                else R.string.income_plan_restored,
                            ),
                            flashTone = MessageTone.Success,
                        )
                    }
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
        _state.update { it.copy(flashMessage = null, flashTone = MessageTone.Success) }
    }
}

private data class IncomePlanSubmissionCallbacks(
    val onDataChanged: () -> Unit,
    val refresh: () -> Unit,
)

private class IncomePlanSubmissionCoordinator(
    private val repository: IncomePlanActions,
    private val state: MutableStateFlow<IncomePlanUiState>,
    private val currentMonthProvider: () -> YearMonth,
    private val callbacks: IncomePlanSubmissionCallbacks,
) {
    fun submit(scope: CoroutineScope) {
        val current = state.value
        if (current.isSubmitting) return
        if (!repository.canModifyLedger()) {
            state.update {
                it.copy(
                    canModify = false,
                    addDraft = it.addDraft.copy(
                        validationError = UiText.res(R.string.common_readonly_ledger),
                    ),
                )
            }
            return
        }
        val validated = current.addDraft.validated() ?: run {
            state.update {
                it.copy(
                    addDraft = it.addDraft.copy(
                        validationError = UiText.res(R.string.income_plan_validation_error),
                    ),
                )
            }
            return
        }
        state.update { it.copy(isSubmitting = true) }
        scope.launch {
            current.editingPlan?.let { baseline ->
                submitEdit(baseline, validated)
            } ?: submitCreate(validated)
        }
    }

    private suspend fun submitCreate(validated: ValidatedIncomePlanDraft) {
        repository.create(validated.asCreateDraft()).fold(
            onSuccess = {
                state.update {
                    it.copy(
                        isSubmitting = false,
                        addDraft = IncomePlanDraftUi(homeCurrency = repository.currentHomeCurrency),
                        flashMessage = UiText.res(R.string.income_plan_added),
                        flashTone = MessageTone.Success,
                        addSucceeded = true,
                        editSucceeded = false,
                    )
                }
                callbacks.onDataChanged()
                callbacks.refresh()
            },
            onFailure = { err ->
                state.update {
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

    private suspend fun submitEdit(
        baseline: IncomePlan,
        validated: ValidatedIncomePlanDraft,
    ) {
        repository.updateAllowingOffline(
            baseline = baseline,
            patch = validated.asPatch(baseline.rowVersion),
        ).fold(
            onSuccess = ::handleEditSuccess,
            onFailure = { err ->
                state.update {
                    it.copy(
                        isSubmitting = false,
                        editSucceeded = false,
                        addDraft = it.addDraft.copy(
                            validationError = err.toUiText(R.string.income_plan_update_failed),
                        ),
                    )
                }
            },
        )
    }

    private fun handleEditSuccess(outcome: IncomePlanSaveOutcome) {
        state.update { current ->
            val updatedPlans = current.activePlans.replaceByPublicId(outcome.plan)
            current.copy(
                isSubmitting = false,
                activePlans = updatedPlans,
                currentMonthSummary = incomePlanMonthSummary(
                    plans = updatedPlans,
                    currentMonth = currentMonthProvider(),
                ),
                flashMessage = when (outcome) {
                    is IncomePlanSaveOutcome.Synced -> UiText.res(R.string.income_plan_updated)
                    is IncomePlanSaveOutcome.Queued -> UiText.res(R.string.income_plan_update_queued)
                },
                flashTone = when (outcome) {
                    is IncomePlanSaveOutcome.Synced -> MessageTone.Success
                    is IncomePlanSaveOutcome.Queued -> MessageTone.Info
                },
                addSucceeded = false,
                editSucceeded = true,
            )
        }
        callbacks.onDataChanged()
    }
}

private fun IncomePlanDraftUi.validated(): ValidatedIncomePlanDraft? {
    val amount = parsedAmountCents() ?: return null
    val payDay = parsedPayDay() ?: return null
    val cleanLabel = label.trim().takeIf(String::isNotEmpty) ?: return null
    val month = when (frequency) {
        IncomeFrequency.ONE_TIME -> parsedIncomeMonth() ?: return null
        IncomeFrequency.MONTHLY -> null
    }
    return ValidatedIncomePlanDraft(
        label = cleanLabel,
        sourceType = sourceType,
        frequency = frequency,
        incomeMonth = month,
        amountCents = amount,
        payDay = payDay,
    )
}

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

private fun List<IncomePlan>.replaceByPublicId(updated: IncomePlan): List<IncomePlan> =
    map { current -> if (current.publicId == updated.publicId) updated else current }
