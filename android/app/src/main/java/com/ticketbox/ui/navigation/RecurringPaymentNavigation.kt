package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringPaymentOriginLookup
import com.ticketbox.data.repository.RecurringPaymentPeriodOccupant
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import java.util.UUID

/** Navigation identity only. CreateExpense / Confirm / link stay on their current owners. */
@JsonClass(generateAdapter = true)
internal data class RecurringPaymentTask(
    val binding: LogicalSessionBinding,
    val seriesPublicId: String,
    val period: String,
    val clientRef: String,
    val merchant: String,
    val recordedCurrencyCode: String?,
    val suggestedAmountMinor: Long?,
    val ledgerHomeCurrencyCode: String,
    val occurrenceRowVersion: Long? = null,
) {
    init {
        if (recordedCurrencyCode == null) require(suggestedAmountMinor == null)
    }

    fun clientRefFor(occurrenceRowVersion: Long, originRef: String?): String =
        originRef ?: clientRef.takeIf { this.occurrenceRowVersion == null || this.occurrenceRowVersion == occurrenceRowVersion }
            ?: UUID.randomUUID().toString()

    fun matchesCurrentGeneration(seriesPublicId: String, period: String, rowVersion: Long): Boolean =
        occurrenceRowVersion != null &&
            occurrenceRowVersion == rowVersion &&
            this.seriesPublicId == seriesPublicId &&
            this.period == period
}

/** Unsubmitted form input for one payment task. Survives ordinary Back; not a financial Writer. */
@JsonClass(generateAdapter = true)
internal data class RecurringPaymentDraft(
    val clientRef: String,
    val amountText: String? = null,
    val currencyCode: String?,
    val merchant: String,
    val category: String,
    val note: String,
    val expenseTime: String,
    val timeFormJson: String? = null,
)

private val recurringPaymentTaskAdapter = Moshi.Builder().build().adapter(RecurringPaymentTask::class.java)
private val recurringPaymentTaskListAdapter = Moshi.Builder().build().adapter<List<RecurringPaymentTask>>(
    Types.newParameterizedType(List::class.java, RecurringPaymentTask::class.java),
)
private val recurringPaymentDraftListAdapter = Moshi.Builder().build().adapter<List<RecurringPaymentDraft>>(
    Types.newParameterizedType(List::class.java, RecurringPaymentDraft::class.java),
)
internal const val RECURRING_PAYMENT_ROUTE = "recurring-payment?task={task}"
private const val RECURRING_PAYMENT_TASKS_KEY = "recurring.payment.tasks"
private const val RECURRING_PAYMENT_DRAFTS_KEY = "recurring.payment.drafts"

internal data class RecurringExpenseNavigation(
    val onOpenExpense: (Long) -> Unit,
    val onRecordPayment: (RecurringPaymentTask) -> Unit = {},
    val onOpenSubmission: (String) -> Unit = {},
)

internal class RecurringPaymentDraftStore(private val state: SavedStateHandle) {
    private val tasks: List<RecurringPaymentTask>
        get() = state.get<String>(RECURRING_PAYMENT_TASKS_KEY)?.let { recurringPaymentTaskListAdapter.fromJson(it) }.orEmpty()
    private val drafts: List<RecurringPaymentDraft>
        get() = state.get<String>(RECURRING_PAYMENT_DRAFTS_KEY)?.let { recurringPaymentDraftListAdapter.fromJson(it) }.orEmpty()

    /**
     * Canonical period task only. Does not delete another clientRef draft.
     * After origin A wins, keep a current-version B draft as the local task anchor until
     * the user reopens or abandons it; do not auto-delete.
     */
    fun remember(task: RecurringPaymentTask) {
        state[RECURRING_PAYMENT_TASKS_KEY] = recurringPaymentTaskListAdapter.toJson(
            tasks.filterNot { it.binding == task.binding && it.seriesPublicId == task.seriesPublicId && it.period == task.period } + task,
        )
    }

    fun remembered(
        binding: LogicalSessionBinding?,
        seriesPublicId: String?,
        period: String?,
    ): RecurringPaymentTask? {
        if (binding == null || seriesPublicId == null || period == null) return null
        return tasks.firstOrNull {
            it.binding == binding && it.seriesPublicId == seriesPublicId && it.period == period
        }
    }

    fun read(clientRef: String): RecurringPaymentDraft? = drafts.firstOrNull { it.clientRef == clientRef }

    fun write(draft: RecurringPaymentDraft) {
        state[RECURRING_PAYMENT_DRAFTS_KEY] = recurringPaymentDraftListAdapter.toJson(
            drafts.filterNot { it.clientRef == draft.clientRef } + draft,
        )
    }

    fun removeDraft(clientRef: String) {
        state[RECURRING_PAYMENT_DRAFTS_KEY] = recurringPaymentDraftListAdapter.toJson(
            drafts.filterNot { it.clientRef == clientRef },
        )
    }

    fun retireTask(clientRef: String) {
        state[RECURRING_PAYMENT_TASKS_KEY] = recurringPaymentTaskListAdapter.toJson(
            tasks.filterNot { it.clientRef == clientRef },
        )
        removeDraft(clientRef)
    }
}

internal fun recurringPaymentTaskJson(task: RecurringPaymentTask): String = recurringPaymentTaskAdapter.toJson(task)

internal fun readRecurringPaymentTask(json: String?): RecurringPaymentTask? =
    json?.let { runCatching { recurringPaymentTaskAdapter.fromJson(it) }.getOrNull() }

internal fun recurringPaymentRoute(task: RecurringPaymentTask): String =
    "recurring-payment?task=${Uri.encode(recurringPaymentTaskJson(task))}"

internal sealed interface OriginObservation {
    data object Loading : OriginObservation
    data object Absent : OriginObservation
    data class Found(val clientRef: String, val acceptedExpenseId: Long? = null) : OriginObservation
    data class Occupied(
        val clientRef: String,
        val acceptedExpenseId: Long? = null,
        val occurrenceRowVersion: Long? = null,
    ) : OriginObservation
    data object Conflict : OriginObservation

    companion object {
        fun fromLookups(
            exact: RecurringPaymentOriginLookup,
            occupant: RecurringPaymentPeriodOccupant,
            generation: Long?,
        ): OriginObservation {
            val found = exact as? RecurringPaymentOriginLookup.Found
            val clientRef = found?.projection?.request?.clientRef?.takeIf { it.isNotBlank() }
            val occupied = occupant as? RecurringPaymentPeriodOccupant.Occupied
            return when {
                exact is RecurringPaymentOriginLookup.Conflict || (found != null && clientRef == null) ||
                    occupant is RecurringPaymentPeriodOccupant.Conflict -> Conflict
                clientRef != null -> Found(clientRef, found.projection.acceptedExpenseId)
                occupied != null -> Occupied(
                    occupied.clientRef,
                    occupied.acceptedExpenseId,
                    occupied.occurrenceRowVersion,
                )
                else -> Absent
            }
        }
    }
}

/** Visible occurrence identity. Not a Writer or Session. */
internal data class RecurringPaymentIdentity(
    val binding: LogicalSessionBinding?,
    val seriesPublicId: String?,
    val period: String?,
    val occurrenceRowVersion: Long? = null,
)

internal data class RecurringPaymentVisible(
    val accessResolved: Boolean,
    val identity: RecurringPaymentIdentity,
    val occurrenceState: String?,
)

internal fun RecurringPaymentTask.matches(identity: RecurringPaymentIdentity): Boolean =
    binding == identity.binding && seriesPublicId == identity.seriesPublicId && period == identity.period

internal fun retainRecurringPaymentTask(
    task: RecurringPaymentTask,
    userClosed: Boolean,
    visible: RecurringPaymentVisible,
): Boolean {
    if (userClosed) return false
    if (!visible.accessResolved) return true
    if (visible.identity.binding != task.binding) return false
    return visible.identity.seriesPublicId != task.seriesPublicId ||
        visible.identity.period != task.period ||
        visible.occurrenceState != "fulfilled"
}

internal fun preferredPaymentExpenseId(
    task: RecurringPaymentTask?,
    admittedExpenseId: Long?,
    visible: RecurringPaymentIdentity,
): Long? {
    if (task == null || admittedExpenseId == null) return null
    if (!task.matches(visible)) return null
    return admittedExpenseId
}

internal fun recurringPaymentObservationsReady(accessResolved: Boolean, admittedResolved: Boolean): Boolean =
    accessResolved && admittedResolved

internal fun recurringPaymentShowsBindingChanged(accessResolved: Boolean, sameBinding: Boolean): Boolean =
    accessResolved && !sameBinding

internal fun recurringPaymentTask(
    state: RecurringOccurrenceUiState,
    existing: RecurringPaymentTask? = null,
    remembered: RecurringPaymentTask? = null,
    admittedClientRef: String? = null,
): RecurringPaymentTask? {
    val binding = state.access?.binding ?: return null
    val item = state.item ?: return null
    val occurrence = state.occurrence ?: return null
    val home = CurrencyCode.fromStorageKeyOrNull(state.ledgerHomeCurrencyCode)?.storageKey ?: return null
    if (!state.canWrite || occurrence.state != "unfulfilled") return null
    val recorded = CurrencyCode.fromStorageKeyOrNull(occurrence.homeCurrencyCode)?.storageKey
    val originRef = admittedClientRef?.takeIf(String::isNotBlank)
    val prior = remembered ?: existing
    if (prior != null && prior.matches(RecurringPaymentIdentity(binding, item.publicId, occurrence.period))) {
        return prior.copy(
            clientRef = prior.clientRefFor(occurrence.rowVersion, originRef),
            occurrenceRowVersion = occurrence.rowVersion,
        )
    }
    return RecurringPaymentTask(
        binding = binding,
        seriesPublicId = item.publicId,
        period = occurrence.period,
        clientRef = originRef ?: UUID.randomUUID().toString(),
        merchant = item.merchant,
        recordedCurrencyCode = recorded,
        suggestedAmountMinor = if (recorded == null) null else occurrence.plannedAmountCents,
        ledgerHomeCurrencyCode = home,
        occurrenceRowVersion = occurrence.rowVersion,
    )
}
