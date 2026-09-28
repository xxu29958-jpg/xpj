package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth
import java.util.UUID

/** Retained by MAIN_ROUTE; listing and forecasts do not own or reinterpret creation input. */
class IncomePlanCreateViewModel(
    private val repository: IncomePlanActions,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    private val _state = MutableStateFlow(IncomePlanCreateUiState())
    val state: StateFlow<IncomePlanCreateUiState> = _state.asStateFlow()
    private val draftStore = IncomePlanCreateDraftStore(savedStateHandle)
    private val inFlight = mutableMapOf<LogicalSessionBinding, IncomePlanCreateSession>()

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess().distinctUntilChanged().collect { access ->
                val binding = access?.binding
                if (binding == _state.value.binding) {
                    _state.update { it.copy(canModify = access?.canModify == true) }
                } else {
                    val session = binding?.let { inFlight[it] ?: draftStore.read(it) }
                    _state.value = IncomePlanCreateUiState(
                        binding = binding, canModify = access?.canModify == true,
                        session = session, isSubmitting = binding?.let { it in inFlight } == true,
                    )
                    if (session != null && binding != null && binding !in inFlight) {
                        retryPublicationRecovery()
                    }
                }
            }
        }
    }

    fun open(expectedBinding: LogicalSessionBinding, month: String, currency: CurrencyCode?) {
        val current = _state.value
        if (expectedBinding != current.binding || current.isRestoring) return
        val retained = inFlight[expectedBinding] ?: draftStore.read(expectedBinding)
        if (retained == null && !current.canModify) return
        val session = retained ?: IncomePlanCreateSession(
            binding = expectedBinding, creationKey = UUID.randomUUID().toString(),
            draft = IncomePlanDraftUi(intentMonth = month, incomeMonthInput = month, homeCurrency = currency),
        )
        draftStore.write(session)
        _state.update { it.copy(session = session, publishedRowId = null,
            isSubmitting = expectedBinding in inFlight) }
        if (retained != null && !_state.value.isSubmitting) retryPublicationRecovery()
    }

    fun updateDraftField(field: IncomePlanDraftField, value: String) {
        mutateDraft { draft ->
            when (field) {
                IncomePlanDraftField.Label -> draft.copy(label = value, validationError = null)
                IncomePlanDraftField.IncomeMonth -> draft.copy(incomeMonthInput = value, validationError = null)
                IncomePlanDraftField.Amount -> draft.copy(amountYuanInput = value).withAmountValidation()
                IncomePlanDraftField.PayDay -> draft.copy(payDayInput = value, validationError = null)
            }
        }
    }

    fun updateDraftChoice(source: IncomeSourceType? = null, frequency: IncomeFrequency? = null) {
        mutateDraft { it.copy(sourceType = source ?: it.sourceType,
            frequency = frequency ?: it.frequency, validationError = null) }
    }

    fun shiftDraftIncomeMonth(deltaMonths: Long) {
        mutateDraft { draft ->
            val current = runCatching { YearMonth.parse(draft.incomeMonthInput.trim()) }.getOrElse {
                runCatching { YearMonth.parse(draft.intentMonth) }.getOrNull() ?: return@mutateDraft draft
            }
            draft.copy(incomeMonthInput = current.plusMonths(deltaMonths).toString(), validationError = null)
        }
    }

    fun cancel() {
        val current = _state.value
        val session = current.session ?: return
        if (current.isSubmitting || current.isRestoring || session.phase != IncomePlanCreationPhase.Draft) return
        draftStore.remove(session)
        _state.update { it.copy(session = null, publishedRowId = null) }
    }

    fun submit() {
        val current = _state.value
        val session = current.session ?: return
        if (session.binding != current.binding || !current.canModify || current.isSubmitting || current.isRestoring || current.publishedRowId != null) return
        if (session.phase != IncomePlanCreationPhase.Draft) { retryPublicationRecovery(); return }
        val draft = session.draft.toRepositoryDraftOrNull()
        if (draft == null) {
            mutateDraft { it.copy(validationError = UiText.res(if (it.homeCurrency == null)
                R.string.currency_unconfirmed_write_blocked else R.string.income_plan_validation_error)) }
            return
        }
        val publishing = session.copy(phase = IncomePlanCreationPhase.Publishing)
        draftStore.write(publishing)
        inFlight[session.binding] = publishing
        _state.update { it.copy(session = publishing, isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.create(session.binding, draft, session.creationKey)
            settleCreation(session, result)
        }
    }

    fun consumePublished() {
        _state.update { it.copy(publishedRowId = null) }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    /** An uncertain snapshot must find its original acceptance before any further admission. */
    fun retryPublicationRecovery() {
        val current = _state.value
        val session = current.session ?: return
        if (current.isSubmitting || current.isRestoring) return
        _state.update { it.copy(isRestoring = true) }
        viewModelScope.launch {
            val result = repository.originalCreation(session.binding, session.creationKey)
            val accepted = result.getOrNull()?.takeIf(session::matchesSubmission)
            val wasDraft = session.phase in setOf(IncomePlanCreationPhase.Draft, IncomePlanCreationPhase.DraftNeedsRecovery)
            val missingDraft = result.isSuccess && result.getOrNull() == null && wasDraft
            val unresolved = if (missingDraft) session.copy(phase = IncomePlanCreationPhase.Draft,
                draft = session.draft.copy(validationError = null).withAmountValidation()) else session.copy(
                phase = if (wasDraft) IncomePlanCreationPhase.DraftNeedsRecovery else IncomePlanCreationPhase.NeedsRecovery,
                draft = session.draft.copy(validationError = result.exceptionOrNull()
                    ?.toUiText(R.string.income_plan_creation_recovery_required)
                    ?: UiText.res(R.string.income_plan_creation_recovery_required)))
            if (accepted != null) draftStore.remove(session) else draftStore.replaceOriginal(unresolved)
            if (_state.value.binding != session.binding || _state.value.session?.creationKey != session.creationKey) return@launch
            _state.update { it.copy(isRestoring = false, session = if (accepted != null) null else unresolved,
                publishedRowId = accepted?.row?.id, flashMessage = if (accepted != null)
                    UiText.res(R.string.income_plan_submission_saved) else it.flashMessage) }
        }
    }

    private fun mutateDraft(transform: (IncomePlanDraftUi) -> IncomePlanDraftUi) {
        val current = _state.value
        val session = current.session ?: return
        if (!current.canModify || current.isSubmitting || current.isRestoring || session.phase != IncomePlanCreationPhase.Draft) return
        val next = session.copy(draft = transform(session.draft))
        draftStore.write(next)
        _state.update { it.copy(session = next) }
    }

    private fun settleCreation(session: IncomePlanCreateSession, result: Result<Long>) {
        inFlight.remove(session.binding)
        val failed = session.copy(draft = session.draft.copy(
            validationError = result.exceptionOrNull()?.toUiText(R.string.income_plan_add_failed)))
        if (result.isSuccess) draftStore.remove(session) else draftStore.replaceOriginal(failed)
        if (_state.value.binding != session.binding || _state.value.session?.creationKey != session.creationKey) return
        _state.update { it.copy(isSubmitting = false, session = if (result.isSuccess) null else failed,
            publishedRowId = result.getOrNull(), flashMessage = if (result.isSuccess)
                UiText.res(R.string.income_plan_submission_saved) else it.flashMessage) }
    }
}
