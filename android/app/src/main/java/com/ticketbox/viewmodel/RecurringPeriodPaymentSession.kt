package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import java.util.UUID

@JsonClass(generateAdapter = true)
data class RecurringPeriodPaymentOrigin(
    val binding: LogicalSessionBinding,
    val seriesPublicId: String,
    val period: String,
    val clientRef: String,
    val merchant: String,
    val obligationCurrencyCode: String?,
    val plannedAmountCents: Long?,
    val ledgerHomeCurrencyCode: String? = null,
    val category: String? = null,
    val note: String? = null,
    val capturedAmountCents: Long? = null,
    val capturedAmountText: String? = null,
    val expenseTime: String? = null,
    val acceptedExpenseId: Long? = null,
    val admitted: Boolean = false,
)

/**
 * Period-payment origin store for the existing occurrence ViewModel.
 * Not a second Owner: CreateExpense / Confirm / link stay on their current writers.
 * Android saved state owns the unsubmitted return-to-period task context.
 */
internal class RecurringPeriodPaymentSession(
    private val current: () -> RecurringOccurrenceUiState,
    private val mutate: ((RecurringOccurrenceUiState) -> RecurringOccurrenceUiState) -> Unit,
    private val load: (String) -> Unit,
    private val savedState: SavedStateHandle,
) {
    private val adapter = Moshi.Builder().build().adapter<List<RecurringPeriodPaymentOrigin>>(
        Types.newParameterizedType(List::class.java, RecurringPeriodPaymentOrigin::class.java),
    )
    private val sessions: MutableMap<Pair<String, String>, RecurringPeriodPaymentOrigin> = run {
        val json = savedState.get<String>(SESSIONS_KEY) ?: return@run mutableMapOf()
        adapter.fromJson(json).orEmpty().associateBy { it.seriesPublicId to it.period }.toMutableMap()
    }

    fun clear() {
        sessions.clear()
        persist()
    }

    fun recordPeriodPayment() {
        val state = current()
        val binding = state.access?.binding ?: return
        val item = state.item ?: return
        val occurrence = state.occurrence ?: return
        if (!state.canWrite || occurrence.state != "unfulfilled") return
        val key = item.publicId to occurrence.period
        val existing = sessions[key] ?: state.periodPaymentOrigin?.takeIf {
            it.seriesPublicId == item.publicId && it.period == occurrence.period
        }
        if (existing?.admitted == true) {
            remember(existing.copy(binding = binding))
            mutate {
                it.copy(
                    periodPaymentOrigin = null,
                    preferredPaymentClientRef = existing.clientRef,
                    preferredPaymentAcceptedExpenseId = existing.acceptedExpenseId?.takeIf { id -> id > 0 },
                )
            }
            return
        }
        if (state.periodPaymentOrigin != null && existing != null) return
        val origin = (existing ?: RecurringPeriodPaymentOrigin(
            binding = binding,
            seriesPublicId = item.publicId,
            period = occurrence.period,
            clientRef = UUID.randomUUID().toString(),
            merchant = item.merchant,
            obligationCurrencyCode = occurrence.homeCurrencyCode,
            plannedAmountCents = occurrence.plannedAmountCents,
            ledgerHomeCurrencyCode = state.ledgerHomeCurrencyCode,
        )).copy(binding = binding)
        remember(origin)
        mutate { it.copy(periodPaymentOrigin = origin) }
    }

    fun capturePeriodPaymentDraft(
        clientRef: String,
        category: String,
        note: String,
        currencyCode: String,
        amountCents: Long,
        merchant: String? = null,
        amountText: String? = null,
        expenseTime: String? = null,
    ) {
        val origin = sessions.values.firstOrNull { it.clientRef == clientRef }
            ?: current().periodPaymentOrigin?.takeIf { it.clientRef == clientRef }
            ?: return
        val updated = origin.copy(
            merchant = merchant ?: origin.merchant,
            category = category,
            note = note,
            obligationCurrencyCode = currencyCode,
            capturedAmountCents = amountCents,
            capturedAmountText = amountText ?: origin.capturedAmountText,
            expenseTime = expenseTime?.takeIf(String::isNotBlank) ?: origin.expenseTime,
        )
        remember(updated)
        mutate { state ->
            if (state.periodPaymentOrigin?.clientRef == clientRef) state.copy(periodPaymentOrigin = updated)
            else state
        }
    }

    fun acceptPeriodPaymentAdmission(clientRef: String, acceptedExpenseId: Long? = null) {
        val origin = sessions.values.firstOrNull { it.clientRef == clientRef }
            ?: current().periodPaymentOrigin?.takeIf { it.clientRef == clientRef }
            ?: return
        val updated = origin.copy(
            admitted = true,
            acceptedExpenseId = acceptedExpenseId?.takeIf { it > 0 } ?: origin.acceptedExpenseId,
        )
        remember(updated)
        mutate { state ->
            if (state.periodPaymentOrigin?.clientRef == clientRef) state.copy(periodPaymentOrigin = updated)
            else state
        }
    }

    fun applyCreateOutcome(
        submitted: RecurringPeriodPaymentOrigin,
        error: UiText?,
        acceptedExpenseId: Long? = null,
    ): Boolean {
        val visible = current().periodPaymentOrigin
        val sameVisible = visible?.clientRef == submitted.clientRef && visible.binding == submitted.binding
        if (error == null) {
            acceptPeriodPaymentAdmission(submitted.clientRef, acceptedExpenseId)
            mutate { state ->
                val currentPeriod = state.occurrence?.period ?: state.requestedPeriod
                val samePeriod = state.item?.publicId == submitted.seriesPublicId && currentPeriod == submitted.period
                val cleared = if (state.periodPaymentInFlightClientRef == submitted.clientRef) {
                    state.copy(periodPaymentInFlightClientRef = null)
                } else state
                if (samePeriod) cleared.copy(
                    preferredPaymentClientRef = submitted.clientRef,
                    preferredPaymentAcceptedExpenseId = acceptedExpenseId?.takeIf { it > 0 }
                        ?: sessions[submitted.seriesPublicId to submitted.period]?.acceptedExpenseId,
                ) else cleared
            }
            if (sameVisible) dismissPeriodPayment()
            return sameVisible
        }
        mutate { state ->
            val cleared = if (state.periodPaymentInFlightClientRef == submitted.clientRef) {
                state.copy(periodPaymentInFlightClientRef = null)
            } else state
            if (sameVisible) cleared.copy(periodPaymentError = error) else cleared
        }
        return false
    }

    fun applyLedgerHome(code: String?) {
        mutate { state ->
            val origin = state.periodPaymentOrigin?.takeIf { it.ledgerHomeCurrencyCode != code }
                ?.copy(ledgerHomeCurrencyCode = code)?.also { remember(it) }
                ?: state.periodPaymentOrigin
            state.copy(ledgerHomeCurrencyCode = code, periodPaymentOrigin = origin)
        }
    }

    fun snapshotPeriodPaymentInputs(
        clientRef: String,
        merchant: String,
        amountText: String,
        expenseTime: String,
    ) {
        val origin = sessions.values.firstOrNull { it.clientRef == clientRef }
            ?: current().periodPaymentOrigin?.takeIf { it.clientRef == clientRef }
            ?: return
        val updated = origin.copy(
            merchant = merchant,
            capturedAmountText = amountText,
            capturedAmountCents = if (amountText.isBlank()) null else origin.capturedAmountCents,
            expenseTime = expenseTime.takeIf { it.isNotBlank() } ?: origin.expenseTime,
        )
        remember(updated)
        mutate { state ->
            if (state.periodPaymentOrigin?.clientRef == clientRef) state.copy(periodPaymentOrigin = updated)
            else state
        }
    }

    fun rememberReturnClientRef(clientRef: String) {
        savedState[RETURN_REF_KEY] = clientRef
    }

    fun consumeReturnClientRef(): String? {
        val ref = savedState.get<String>(RETURN_REF_KEY)?.takeIf(String::isNotBlank)
        savedState[RETURN_REF_KEY] = null
        return ref
    }

    fun retireCompleted(seriesPublicId: String, period: String) {
        if (sessions.remove(seriesPublicId to period) == null) return
        persist()
    }

    fun restoreAdmittedPeriodOccurrence(items: List<RecurringItem> = emptyList(), clientRef: String? = null) {
        val wanted = clientRef?.takeIf(String::isNotBlank) ?: current().preferredPaymentClientRef
        val session = if (wanted.isNullOrBlank()) {
            sessions.values.lastOrNull { it.admitted }
        } else {
            sessions.values.lastOrNull { it.admitted && it.clientRef == wanted }
        } ?: return
        val item = current().item?.takeIf { it.publicId == session.seriesPublicId }
            ?: items.firstOrNull { it.publicId == session.seriesPublicId }
            ?: return
        val binding = current().access?.binding
        if (item.ledgerId != binding?.ledgerId) return
        mutate {
            it.copy(
                item = item,
                occurrence = null,
                choice = null,
                acceptedId = null,
                message = null,
                requestedPeriod = session.period,
                periodPaymentOrigin = null,
                preferredPaymentClientRef = session.clientRef,
                preferredPaymentAcceptedExpenseId = session.acceptedExpenseId?.takeIf { id -> id > 0 },
            )
        }
        load(session.period)
    }

    fun sessionForSeries(seriesPublicId: String): RecurringPeriodPaymentOrigin? =
        sessions.values.lastOrNull { it.seriesPublicId == seriesPublicId && !it.admitted }

    fun rememberAcceptedExpenseId(clientRef: String?, acceptedExpenseId: Long) {
        val ref = clientRef?.takeIf(String::isNotBlank) ?: return
        if (acceptedExpenseId <= 0) return
        val origin = sessions.values.firstOrNull { it.clientRef == ref } ?: return
        if (origin.acceptedExpenseId == acceptedExpenseId) return
        remember(origin.copy(acceptedExpenseId = acceptedExpenseId))
    }

    fun choosePeriodPaymentCurrency(code: String) {
        val origin = current().periodPaymentOrigin ?: return
        if (CurrencyCode.fromStorageKeyOrNull(origin.obligationCurrencyCode) != null) return
        val chosen = CurrencyCode.fromStorageKeyOrNull(code) ?: return
        val updated = origin.copy(
            obligationCurrencyCode = chosen.storageKey,
            plannedAmountCents = null,
            capturedAmountCents = null,
            capturedAmountText = null,
        )
        remember(updated)
        mutate {
            if (it.periodPaymentOrigin?.clientRef == origin.clientRef) it.copy(periodPaymentOrigin = updated)
            else it
        }
    }

    fun dismissPeriodPayment() {
        val visible = current().periodPaymentOrigin
        mutate { state ->
            val inFlight = state.periodPaymentInFlightClientRef
            state.copy(
                periodPaymentOrigin = null,
                periodPaymentError = null,
                periodPaymentInFlightClientRef = if (inFlight != null && visible?.clientRef == inFlight) {
                    null
                } else inFlight,
            )
        }
    }

    fun restoreVisibleOrigin() {
        val state = current()
        val item = state.item ?: return
        val period = state.occurrence?.period ?: return
        val session = sessions[item.publicId to period] ?: return
        if (session.admitted) {
            mutate {
                it.copy(
                    preferredPaymentClientRef = session.clientRef,
                    preferredPaymentAcceptedExpenseId = session.acceptedExpenseId?.takeIf { id -> id > 0 },
                )
            }
            return
        }
        mutate {
            it.copy(periodPaymentOrigin = session.copy(binding = state.access?.binding ?: session.binding))
        }
    }

    private fun remember(origin: RecurringPeriodPaymentOrigin) {
        sessions[origin.seriesPublicId to origin.period] = origin
        persist()
    }

    private fun persist() {
        savedState[SESSIONS_KEY] = adapter.toJson(sessions.values.toList())
    }

    private companion object {
        const val SESSIONS_KEY = "recurring.periodPayment.sessions"
        const val RETURN_REF_KEY = "recurring.periodPayment.returnClientRef"
    }
}
