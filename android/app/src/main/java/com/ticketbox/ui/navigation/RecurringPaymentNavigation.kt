package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LegacyPeriodPaymentSession
import com.ticketbox.data.repository.LogicalSessionBinding
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
) {
    init {
        if (recordedCurrencyCode == null) require(suggestedAmountMinor == null)
    }
}

/** Unsubmitted form input for one payment task. Survives ordinary Back; not a financial Writer. */
@JsonClass(generateAdapter = true)
internal data class RecurringPaymentDraft(
    val clientRef: String,
    val amountText: String,
    val currencyCode: String?,
    val merchant: String,
    val category: String,
    val note: String,
    val expenseTime: String,
)

private val recurringPaymentTaskAdapter = Moshi.Builder().build().adapter(RecurringPaymentTask::class.java)
private val recurringPaymentTaskListAdapter = Moshi.Builder().build().adapter<List<RecurringPaymentTask>>(
    Types.newParameterizedType(List::class.java, RecurringPaymentTask::class.java),
)
private val recurringPaymentDraftListAdapter = Moshi.Builder().build().adapter<List<RecurringPaymentDraft>>(
    Types.newParameterizedType(List::class.java, RecurringPaymentDraft::class.java),
)
private val legacyPeriodPaymentSessionListAdapter = Moshi.Builder().build().adapter<List<LegacyPeriodPaymentSession>>(
    Types.newParameterizedType(List::class.java, LegacyPeriodPaymentSession::class.java),
)
internal const val RECURRING_PAYMENT_ROUTE = "recurring-payment?task={task}"
internal const val LEGACY_PERIOD_PAYMENT_SESSIONS_KEY = "recurring.periodPayment.sessions"
private const val RECURRING_PAYMENT_TASKS_KEY = "recurring.payment.tasks"
private const val RECURRING_PAYMENT_DRAFTS_KEY = "recurring.payment.drafts"

internal data class RecurringExpenseNavigation(
    val onOpenExpense: (Long) -> Unit,
    val onRecordPayment: (RecurringPaymentTask) -> Unit = {},
)

internal class RecurringPaymentDraftStore(private val state: SavedStateHandle) {
    private val tasks: List<RecurringPaymentTask>
        get() = state.get<String>(RECURRING_PAYMENT_TASKS_KEY)?.let { recurringPaymentTaskListAdapter.fromJson(it) }.orEmpty()
    private val drafts: List<RecurringPaymentDraft>
        get() = state.get<String>(RECURRING_PAYMENT_DRAFTS_KEY)?.let { recurringPaymentDraftListAdapter.fromJson(it) }.orEmpty()

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

    fun adoptLegacyPeriodPaymentSessions(source: SavedStateHandle) {
        val json = source.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) ?: return
        val sessions = runCatching { legacyPeriodPaymentSessionListAdapter.fromJson(json) }.getOrNull() ?: return
        sessions.forEach { session ->
            val home = session.ledgerHomeCurrencyCode ?: return@forEach
            if (session.clientRef.isBlank() || session.seriesPublicId.isBlank() || session.period.isBlank()) return@forEach
            remember(
                RecurringPaymentTask(
                    binding = session.binding,
                    seriesPublicId = session.seriesPublicId,
                    period = session.period,
                    clientRef = session.clientRef,
                    merchant = session.merchant,
                    recordedCurrencyCode = session.obligationCurrencyCode,
                    suggestedAmountMinor = if (session.obligationCurrencyCode == null) null else session.plannedAmountCents,
                    ledgerHomeCurrencyCode = home,
                ),
            )
        }
        source.remove<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
    }
}

internal fun recurringPaymentTaskJson(task: RecurringPaymentTask): String = recurringPaymentTaskAdapter.toJson(task)

internal fun readRecurringPaymentTask(json: String?): RecurringPaymentTask? =
    json?.let { runCatching { recurringPaymentTaskAdapter.fromJson(it) }.getOrNull() }

internal fun recurringPaymentRoute(task: RecurringPaymentTask): String =
    "recurring-payment?task=${Uri.encode(recurringPaymentTaskJson(task))}"

/** Visible occurrence identity. Not a Writer or Session. */
internal data class RecurringPaymentIdentity(
    val binding: LogicalSessionBinding?,
    val seriesPublicId: String?,
    val period: String?,
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
    val prior = remembered ?: existing
    if (prior?.binding == binding && prior.seriesPublicId == item.publicId && prior.period == occurrence.period) {
        return prior
    }
    return RecurringPaymentTask(
        binding = binding,
        seriesPublicId = item.publicId,
        period = occurrence.period,
        clientRef = admittedClientRef?.takeIf { it.isNotBlank() } ?: UUID.randomUUID().toString(),
        merchant = item.merchant,
        recordedCurrencyCode = recorded,
        suggestedAmountMinor = if (recorded == null) null else occurrence.plannedAmountCents,
        ledgerHomeCurrencyCode = home,
    )
}
