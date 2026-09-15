package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.data.repository.OccurrencePaymentDraft
import com.ticketbox.data.repository.PendingOccurrencePayment
import com.ticketbox.data.repository.RecurringOccurrenceActions
import com.ticketbox.data.repository.occurrenceTarget
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import java.time.YearMonth
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RecurringOccurrenceUiState(
    val access: LedgerAccessContext? = null,
    val item: RecurringItem? = null,
    val occurrence: RecurringOccurrenceDto? = null,
    val payments: List<ConfirmedStreamItem> = emptyList(),
    val queue: List<PendingOccurrencePayment> = emptyList(),
    val choice: OccurrencePaymentDraft? = null,
    val loading: Boolean = false,
    val saving: Boolean = false,
    val acceptedId: Long? = null,
    val requestedPeriod: String = "current",
    val message: UiText? = null,
    val periodPaymentOrigin: RecurringPeriodPaymentOrigin? = null,
    val ledgerHomeCurrencyCode: String? = null,
    val periodPaymentInFlightClientRef: String? = null,
    val periodPaymentError: UiText? = null,
    val preferredPaymentClientRef: String? = null,
    val preferredPaymentAcceptedExpenseId: Long? = null,
) {
    val periodPaymentSaving: Boolean
        get() = periodPaymentInFlightClientRef != null &&
            periodPaymentOrigin?.clientRef == periodPaymentInFlightClientRef
    val seriesPending: List<PendingOccurrencePayment> get() = queue.filter {
        it.row.status != PendingMutationStatus.Done && it.row.targetId.startsWith("recurring_occurrence:" + item?.publicId + ":")
    }
    val pending: List<PendingOccurrencePayment> get() = queue.filter {
        it.row.status != PendingMutationStatus.Done &&
            it.row.targetId == occurrenceTarget(item?.publicId.orEmpty(), occurrence?.period ?: requestedPeriod)
    }
    val canWrite: Boolean get() = access?.canModify == true && item?.status != "archived" &&
        occurrence?.state in setOf("unfulfilled", "fulfilled", "needs_review") && !loading && !saving &&
        pending.isEmpty() && (acceptedId == null || queue.any { it.row.id == acceptedId && it.row.status == PendingMutationStatus.Done })
}

class RecurringOccurrenceViewModel(
    private val repository: RecurringOccurrenceActions,
    private val ledger: LedgerActions,
    private val debts: DebtActions,
    private val onChanged: () -> Unit = {},
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    private val mutableState = MutableStateFlow(RecurringOccurrenceUiState(access = repository.currentAccess()))
    val uiState = mutableState.asStateFlow()
    private var epoch = 0L
    internal val periodPayment = RecurringPeriodPaymentSession(
        current = { mutableState.value },
        mutate = { reducer -> mutableState.update(reducer) },
        load = ::load,
        savedState = savedStateHandle,
    )

    init {
        viewModelScope.launch {
            repository.observeAccess().collectLatest { access ->
                if (mutableState.value.access?.binding != access?.binding) {
                    epoch++
                    periodPayment.clear()
                    mutableState.value = RecurringOccurrenceUiState(access = access)
                } else mutableState.update { it.copy(access = access) }
                if (access != null) coroutineScope {
                    launch {
                        ledger.observeConfirmedStream().collect { rows ->
                            mutableState.update { state ->
                                val accepted = state.preferredPaymentAcceptedExpenseId
                                    ?: acceptedExpenseIdForClientRef(rows, state.preferredPaymentClientRef)
                                if (accepted != null) {
                                    periodPayment.rememberAcceptedExpenseId(state.preferredPaymentClientRef, accepted)
                                }
                                state.copy(payments = rows, preferredPaymentAcceptedExpenseId = accepted)
                            }
                        }
                    }
                    repository.observeQueue(access.binding).collect(::acceptQueue)
                }
            }
        }
    }

    fun open(item: RecurringItem) {
        if (item.ledgerId != mutableState.value.access?.binding?.ledgerId) return
        val session = periodPayment.sessionForSeries(item.publicId)
        mutableState.update {
            it.copy(
                item = item,
                occurrence = null,
                choice = null,
                acceptedId = null,
                message = null,
                requestedPeriod = session?.period ?: "current",
                periodPaymentOrigin = null,
                periodPaymentError = null,
                preferredPaymentClientRef = session?.takeIf { origin -> origin.admitted }?.clientRef,
                preferredPaymentAcceptedExpenseId = session?.takeIf { origin -> origin.admitted }?.acceptedExpenseId,
            )
        }
        load(session?.period ?: "current")
    }

    fun dismiss() {
        if (mutableState.value.saving) return
        epoch++
        mutableState.update { it.copy(item = null, occurrence = null, choice = null, loading = false, periodPaymentOrigin = null, periodPaymentError = null) }
    }

    fun changePeriod(period: String) {
        if (runCatching { YearMonth.parse(period).toString() == period }.getOrDefault(false)) {
            mutableState.update { it.copy(occurrence = null, choice = null, acceptedId = null, requestedPeriod = period, periodPaymentOrigin = null, preferredPaymentClientRef = null, preferredPaymentAcceptedExpenseId = null) }
            load(period)
        } else mutableState.update { it.copy(message = UiText.res(R.string.occurrence_invalid_month)) }
    }

    fun refresh() {
        load(mutableState.value.occurrence?.period ?: mutableState.value.requestedPeriod)
    }

    fun restoreAdmittedPeriodOccurrence(items: List<RecurringItem> = emptyList(), clientRef: String? = null) {
        periodPayment.restoreAdmittedPeriodOccurrence(
            items,
            clientRef ?: periodPayment.consumeReturnClientRef(),
        )
    }

    fun createPeriodPayment(draft: ExpenseDraft, onAdmitted: (String) -> Unit = {}) {
        val submitted = mutableState.value.periodPaymentOrigin ?: return
        if (mutableState.value.access?.binding != submitted.binding || mutableState.value.periodPaymentSaving) return
        periodPayment.capturePeriodPaymentDraft(
            submitted.clientRef,
            draft.category.orEmpty(),
            draft.note.orEmpty(),
            draft.originalCurrencyCode?.storageKey ?: submitted.obligationCurrencyCode.orEmpty(),
            draft.originalAmountMinor ?: draft.amountCents ?: 0L,
            merchant = draft.merchant.orEmpty(),
            amountText = submitted.capturedAmountText,
            expenseTime = draft.expenseTime,
        )
        mutableState.update { it.copy(periodPaymentInFlightClientRef = submitted.clientRef, periodPaymentError = null) }
        viewModelScope.launch {
            val result = ledger.createManualExpense(
                draft.copy(
                    clientRef = submitted.clientRef,
                    ledgerHomeCurrency = draft.ledgerHomeCurrency
                        ?: CurrencyCode.fromStorageKeyOrNull(submitted.ledgerHomeCurrencyCode),
                ),
                submitted.binding,
            )
            if (mutableState.value.access?.binding != submitted.binding) return@launch
            val error = if (result.isSuccess) null
                else result.exceptionOrNull()?.message?.let(UiText::raw)
                    ?: UiText.res(R.string.ledger_msg_manual_save_failed)
            val acceptedExpenseId = result.getOrNull()?.id
            if (periodPayment.applyCreateOutcome(submitted, error, acceptedExpenseId)) {
                periodPayment.rememberReturnClientRef(submitted.clientRef)
                onAdmitted(submitted.clientRef)
            }
        }
    }

    fun choose(payment: ConfirmedStreamItem.ExpenseRow?) {
        val state = mutableState.value
        val occurrence = state.occurrence ?: return
        if (!state.canWrite) return
        val root = payment?.root
        mutableState.update { it.copy(choice = OccurrencePaymentDraft(
            occurrence = occurrence,
            seriesLabel = state.item?.merchant.orEmpty(),
            request = RecurringOccurrencePaymentRequestDto(
                action = if (payment == null) "clear" else "link",
                expectedRowVersion = occurrence.rowVersion,
                expectedSeriesRowVersion = occurrence.seriesRowVersion,
                expensePublicId = root?.publicId,
                expectedExpenseRowVersion = root?.rowVersion,
            ),
            paymentLabel = root?.merchant,
            paymentAmountCents = root?.amountCents,
            paymentCurrencyCode = root?.homeCurrencyCode,
        )) }
    }

    fun submit() {
        val state = mutableState.value
        val binding = state.access?.binding ?: return
        val choice = state.choice ?: return
        if (!state.canWrite) return
        mutableState.update { it.copy(saving = true, message = null) }
        viewModelScope.launch {
            val result = repository.enqueue(binding, choice)
            if (mutableState.value.access?.binding != binding) return@launch
            if (result.isSuccess && choice.request.action == "link") {
                mutableState.value.item?.publicId?.let { seriesId ->
                    periodPayment.retireCompleted(seriesId, choice.occurrence.period)
                }
            }
            mutableState.update { it.copy(
                saving = false,
                acceptedId = result.getOrNull(),
                choice = if (result.isSuccess) null else choice,
                message = if (result.isSuccess) UiText.res(R.string.occurrence_saved_locally)
                    else result.exceptionOrNull()?.message?.let(UiText::raw) ?: UiText.res(R.string.occurrence_save_failed),
            ) }
        }
    }

    fun recover(pending: PendingOccurrencePayment, drop: Boolean) {
        if (pending !in mutableState.value.seriesPending) return
        val binding = mutableState.value.access?.binding ?: return
        viewModelScope.launch {
            val result = repository.recover(binding, pending.row, drop)
            if (mutableState.value.access?.binding != binding) return@launch
            if (result.isSuccess) {
                mutableState.update { it.copy(acceptedId = null, choice = null) }
                refresh()
            } else {
                mutableState.update { it.copy(message = result.exceptionOrNull()?.toUiText(R.string.occurrence_save_failed)) }
            }
        }
    }

    private fun load(period: String) {
        val state = mutableState.value
        val binding = state.access?.binding ?: return
        val item = state.item ?: return
        val requestEpoch = ++epoch
        mutableState.update { it.copy(loading = true, message = null) }
        viewModelScope.launch {
            val result = repository.fetch(binding, item.publicId, period)
            if (requestEpoch != epoch || mutableState.value.access?.binding != binding) return@launch
            mutableState.update { it.copy(
                loading = false, occurrence = result.getOrNull() ?: it.occurrence,
                message = if (result.isFailure) UiText.res(R.string.occurrence_refresh_failed) else null,
            ) }
            result.getOrNull()?.takeIf { it.state == "fulfilled" }?.let { occurrence ->
                periodPayment.retireCompleted(item.publicId, occurrence.period)
            }
            val listed = debts.listDebts()
            periodPayment.restoreVisibleOrigin()
            if (requestEpoch == epoch && mutableState.value.access?.binding == binding) {
                listed.onSuccess { page ->
                    periodPayment.applyLedgerHome(resolveLedgerCurrency(page)?.storageKey)
                }
            }
            if (result.isSuccess) ledger.syncConfirmed().onFailure {
                if (requestEpoch == epoch) mutableState.update { it.copy(message = UiText.res(R.string.occurrence_payment_refresh_failed)) }
            }
        }
    }

    private fun acceptedExpenseIdForClientRef(
        rows: List<ConfirmedStreamItem>,
        clientRef: String?,
    ): Long? {
        val ref = clientRef?.takeIf(String::isNotBlank) ?: return null
        return rows.filterIsInstance<ConfirmedStreamItem.ExpenseRow>()
            .firstOrNull { it.root.clientRef == ref }?.root?.id?.takeIf { it > 0 }
    }

    private fun acceptQueue(rows: List<PendingOccurrencePayment>) {
        val previousDone = mutableState.value.queue.filter { it.row.status == PendingMutationStatus.Done }.map { it.row.id }.toSet()
        mutableState.update { it.copy(queue = rows) }
        if (rows.any { it.row.status == PendingMutationStatus.Done && it.row.id !in previousDone }) {
            onChanged()
            if (mutableState.value.item != null) refresh()
        }
    }
}
