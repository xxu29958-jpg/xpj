package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.RecurringItem
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
    private val sessions = restore()

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

    fun capturePeriodPaymentDraft(category: String, note: String, currencyCode: String, amountCents: Long) {
        val origin = current().periodPaymentOrigin ?: return
        val updated = origin.copy(
            category = category,
            note = note,
            obligationCurrencyCode = currencyCode,
            capturedAmountCents = amountCents,
        )
        remember(updated)
        mutate { it.copy(periodPaymentOrigin = updated) }
    }

    fun acceptPeriodPaymentAdmission() {
        val origin = current().periodPaymentOrigin ?: return
        val updated = origin.copy(admitted = true)
        remember(updated)
        mutate { it.copy(periodPaymentOrigin = updated) }
    }

    fun applyLedgerHome(code: String?) {
        mutate { state ->
            val origin = state.periodPaymentOrigin?.takeIf { it.ledgerHomeCurrencyCode != code }
                ?.copy(ledgerHomeCurrencyCode = code)?.also { remember(it) }
                ?: state.periodPaymentOrigin
            state.copy(ledgerHomeCurrencyCode = code, periodPaymentOrigin = origin)
        }
    }

    fun restoreAdmittedPeriodOccurrence(items: List<RecurringItem> = emptyList()) {
        val session = sessions.values.lastOrNull { it.admitted } ?: return
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
            )
        }
        load(session.period)
    }

    fun dismissPeriodPayment() {
        mutate { it.copy(periodPaymentOrigin = null, periodPaymentSaving = false, periodPaymentError = null) }
    }

    fun restoreVisibleOrigin() {
        val state = current()
        val item = state.item ?: return
        val period = state.occurrence?.period ?: return
        val session = sessions[item.publicId to period] ?: return
        if (session.admitted) return
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

    private fun restore(): MutableMap<Pair<String, String>, RecurringPeriodPaymentOrigin> {
        val json = savedState.get<String>(SESSIONS_KEY) ?: return mutableMapOf()
        return adapter.fromJson(json).orEmpty().associateBy { it.seriesPublicId to it.period }.toMutableMap()
    }

    private companion object {
        const val SESSIONS_KEY = "recurring.periodPayment.sessions"
    }
}
