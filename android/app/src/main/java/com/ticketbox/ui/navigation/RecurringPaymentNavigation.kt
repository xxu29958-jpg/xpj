package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.ExpenseManualCreation
import com.ticketbox.data.repository.LegacyPeriodPaymentSession
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginAdopt
import com.ticketbox.data.repository.RecurringPaymentOriginLookup
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.UUID
import kotlinx.coroutines.flow.first

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
private val logicalSessionBindingAdapter = Moshi.Builder().build().adapter(LogicalSessionBinding::class.java)
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
        val previous = tasks.firstOrNull {
            it.binding == task.binding && it.seriesPublicId == task.seriesPublicId && it.period == task.period
        }
        state[RECURRING_PAYMENT_TASKS_KEY] = recurringPaymentTaskListAdapter.toJson(
            tasks.filterNot { it.binding == task.binding && it.seriesPublicId == task.seriesPublicId && it.period == task.period } + task,
        )
        if (previous != null && previous.clientRef != task.clientRef) {
            removeDraft(previous.clientRef)
        }
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

    fun legacyPeriodPaymentSessions(
        source: SavedStateHandle,
    ): List<LeftoverSessionView>? {
        val json = source.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) ?: return emptyList()
        val sessions = runCatching { legacyPeriodPaymentSessionListAdapter.fromJson(json) }.getOrNull() ?: return null
        return sessions.mapNotNull { session ->
            val task = session.toRecurringPaymentTaskOrNull() ?: return@mapNotNull null
            LeftoverSessionView(task, session.toRecurringPaymentDraftOrNull(), session.admitted)
        }
    }

    suspend fun adoptLegacyPeriodPaymentSessions(
        source: SavedStateHandle,
        creation: ExpenseManualCreation,
        identity: RecurringPaymentIdentity? = null,
        continueUnproven: Boolean = false,
    ): LeftoverAdoptNotice {
        val current = identity ?: return LeftoverAdoptNotice.Done
        val generation = current.occurrenceRowVersion ?: return LeftoverAdoptNotice.Done
        val json = source.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
        if (json == null) {
            current.rememberLeftoverSeen(source, false)
            return LeftoverAdoptNotice.Done
        }
        val sessions = runCatching { legacyPeriodPaymentSessionListAdapter.fromJson(json) }.getOrNull()
            ?: return LeftoverAdoptNotice.Done
        val seen = current.leftoverSeen(source)
        val decision = current.leftoverTransition(seen)
        if (continueUnproven) {
            when (current.leftoverContinueDecision(creation)) {
                LeftoverContinueDecision.KeepExistingOrigin -> return LeftoverAdoptNotice.ExistingOrigin
                LeftoverContinueDecision.KeepConflict -> return LeftoverAdoptNotice.Conflict
                LeftoverContinueDecision.Capture -> Unit
            }
        }
        val remaining = current.leftoverApplySessions(sessions, creation, continueUnproven, seen) {
            captureLegacy(it, generation)
        }
        if (remaining.isEmpty()) source.remove<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
        else source[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = legacyPeriodPaymentSessionListAdapter.toJson(remaining)
        current.rememberLeftoverSeen(source, leftoverUnresolved(source, current) && decision == LeftoverTransition.Adopt && !continueUnproven)
        return LeftoverAdoptNotice.Done
    }

    fun leftoverUnresolved(
        source: SavedStateHandle,
        identity: RecurringPaymentIdentity,
    ): Boolean {
        val json = source.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY) ?: return false
        val sessions = runCatching { legacyPeriodPaymentSessionListAdapter.fromJson(json) }.getOrNull() ?: return true
        return sessions.any {
            it.binding == identity.binding &&
                it.seriesPublicId == identity.seriesPublicId &&
                it.period == identity.period
        }
    }

    fun retireFulfilledLegacySessions(
        source: SavedStateHandle,
        identity: RecurringPaymentIdentity,
        dropUnreadable: Boolean = false,
    ) {
        val json = source.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
        if (json == null) {
            identity.rememberLeftoverSeen(source, false)
            return
        }
        val sessions = runCatching { legacyPeriodPaymentSessionListAdapter.fromJson(json) }.getOrNull()
        if (sessions == null) {
            if (dropUnreadable) {
                source.remove<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
                identity.rememberLeftoverSeen(source, false)
            }
            return
        }
        val remaining = sessions.filterNot {
            it.binding == identity.binding &&
                it.seriesPublicId == identity.seriesPublicId &&
                it.period == identity.period
        }
        if (remaining.size != sessions.size) {
            if (remaining.isEmpty()) source.remove<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY)
            else source[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = legacyPeriodPaymentSessionListAdapter.toJson(remaining)
        }
        identity.rememberLeftoverSeen(source, false)
    }

    private fun captureLegacy(session: LegacyPeriodPaymentSession, occurrenceRowVersion: Long) {
        val task = session.toRecurringPaymentTaskOrNull()?.copy(occurrenceRowVersion = occurrenceRowVersion) ?: return
        remember(task)
        val draft = session.toRecurringPaymentDraftOrNull()
        if (draft != null && read(task.clientRef) == null) write(draft)
    }
}

private fun LegacyPeriodPaymentSession.toRecurringPaymentTaskOrNull(): RecurringPaymentTask? {
    val home = ledgerHomeCurrencyCode?.takeIf { it.isNotBlank() } ?: return null
    if (clientRef.isBlank() || seriesPublicId.isBlank() || period.isBlank()) return null
    return RecurringPaymentTask(
        binding = binding,
        seriesPublicId = seriesPublicId,
        period = period,
        clientRef = clientRef,
        merchant = merchant,
        recordedCurrencyCode = obligationCurrencyCode,
        suggestedAmountMinor = if (obligationCurrencyCode == null) null else plannedAmountCents,
        ledgerHomeCurrencyCode = home,
    )
}

private fun LegacyPeriodPaymentSession.toRecurringPaymentDraftOrNull(): RecurringPaymentDraft? {
    val currency = obligationCurrencyCode?.takeIf { it.isNotBlank() }
    val amountText = capturedAmountCents?.let { captured ->
        currency?.let { CurrencyCode.fromStorageKeyOrNull(it) }?.let { formatMinorAmountInput(captured, it) }
    }
    val category = category?.takeIf { it.isNotBlank() }
    val note = note?.takeIf { it.isNotBlank() }
    if (amountText == null && category == null && note == null) return null
    return RecurringPaymentDraft(
        clientRef = clientRef,
        amountText = amountText,
        currencyCode = currency,
        merchant = merchant,
        category = category.orEmpty(),
        note = note.orEmpty(),
        expenseTime = "",
    )
}

internal fun recurringPaymentTaskJson(task: RecurringPaymentTask): String = recurringPaymentTaskAdapter.toJson(task)

internal fun readRecurringPaymentTask(json: String?): RecurringPaymentTask? =
    json?.let { runCatching { recurringPaymentTaskAdapter.fromJson(it) }.getOrNull() }

internal fun recurringPaymentRoute(task: RecurringPaymentTask): String =
    "recurring-payment?task=${Uri.encode(recurringPaymentTaskJson(task))}"

internal enum class LeftoverTransition { Adopt, Retire, Hold }

internal enum class LeftoverContinueDecision { Capture, KeepExistingOrigin, KeepConflict }

internal enum class LeftoverAdoptNotice {
    Done,
    ExistingOrigin,
    Conflict,
    Failed,
    ;

    fun nextHandoff(previous: Result<Unit>?): Result<Unit>? = when (this) {
        Done -> Result.success(Unit)
        else -> previous
    }

    companion object {
        fun blocked(handoff: Result<Unit>?, unresolved: Boolean): Boolean =
            handoff?.isFailure == true || (handoff != null && unresolved)

        fun remembered(handoff: Result<Unit>?, load: () -> RecurringPaymentTask?): RecurringPaymentTask? =
            if (handoff?.isSuccess == true) load() else null

        fun run(block: () -> Unit): LeftoverAdoptNotice = try {
            block()
            Done
        } catch (_: Exception) {
            Failed
        }

        suspend fun runSuspend(block: suspend () -> LeftoverAdoptNotice): LeftoverAdoptNotice = try {
            block()
        } catch (cancelled: kotlin.coroutines.cancellation.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            Failed
        }
    }
}

internal data class LeftoverSessionView(
    val task: RecurringPaymentTask,
    val draft: RecurringPaymentDraft?,
    val admitted: Boolean,
)

/** Visible occurrence identity. Not a Writer or Session. */
internal data class RecurringPaymentIdentity(
    val binding: LogicalSessionBinding?,
    val seriesPublicId: String?,
    val period: String?,
    val occurrenceRowVersion: Long? = null,
) {
    fun matchesLoadedSession(session: LegacyPeriodPaymentSession): Boolean =
        occurrenceRowVersion != null &&
            binding == session.binding &&
            seriesPublicId == session.seriesPublicId &&
            period == session.period &&
            session.clientRef.isNotBlank()

    fun leftoverSeenKey(): String? {
        val bound = binding ?: return null
        val series = seriesPublicId?.takeIf { it.isNotBlank() } ?: return null
        val month = period?.takeIf { it.isNotBlank() } ?: return null
        return "recurring.periodPayment.seen:${URLEncoder.encode(logicalSessionBindingAdapter.toJson(bound), StandardCharsets.UTF_8.name())}:$series:$month"
    }

    fun leftoverSeen(source: SavedStateHandle): Long? = leftoverSeenKey()?.let { source.get<Long>(it) }

    fun rememberLeftoverSeen(source: SavedStateHandle, keep: Boolean) {
        val key = leftoverSeenKey() ?: return
        if (keep) source[key] = occurrenceRowVersion ?: return
        else source.remove<Long>(key)
    }

    fun leftoverContinueAvailable(sessions: List<LeftoverSessionView>?): Boolean =
        sessions.orEmpty().any {
            !it.admitted &&
                it.task.binding == binding &&
                it.task.seriesPublicId == seriesPublicId &&
                it.task.period == period
        }

    fun leftoverContinueVisible(
        sessions: List<LeftoverSessionView>?,
        seen: Long?,
        handoffFailed: Boolean,
        ready: Boolean,
    ): Boolean {
        if (!ready || sessions == null || !leftoverContinueAvailable(sessions)) return false
        return leftoverTransition(seen) == LeftoverTransition.Hold || handoffFailed
    }

    suspend fun leftoverContinueDecision(creation: ExpenseManualCreation): LeftoverContinueDecision {
        val bound = binding ?: return LeftoverContinueDecision.KeepConflict
        val series = seriesPublicId?.takeIf { it.isNotBlank() } ?: return LeftoverContinueDecision.KeepConflict
        val month = period?.takeIf { it.isNotBlank() } ?: return LeftoverContinueDecision.KeepConflict
        return when (creation.observeOrigin(bound, RecurringPaymentOrigin(series, month, occurrenceRowVersion)).first()) {
            is RecurringPaymentOriginLookup.Found -> LeftoverContinueDecision.KeepExistingOrigin
            RecurringPaymentOriginLookup.Conflict -> LeftoverContinueDecision.KeepConflict
            RecurringPaymentOriginLookup.Absent -> LeftoverContinueDecision.Capture
        }
    }

    suspend fun leftoverApplySessions(
        sessions: List<LegacyPeriodPaymentSession>,
        creation: ExpenseManualCreation,
        continueUnproven: Boolean,
        seen: Long?,
        capture: (LegacyPeriodPaymentSession) -> Unit,
    ): List<LegacyPeriodPaymentSession> {
        val decision = leftoverTransition(seen)
        return when {
            continueUnproven -> adoptLoadedSessions(sessions, creation, bind = false, capture)
            decision == LeftoverTransition.Retire -> sessions.filterNot(::matchesLoadedSession)
            decision == LeftoverTransition.Adopt -> adoptLoadedSessions(sessions, creation, bind = true, capture)
            else -> sessions
        }
    }

    fun leftoverTransition(seen: Long?): LeftoverTransition {
        val current = occurrenceRowVersion ?: return LeftoverTransition.Hold
        if (seen != null && current > seen) return LeftoverTransition.Retire
        if (seen != null && current == seen) return LeftoverTransition.Adopt
        if (seen == null && current == 0L) return LeftoverTransition.Adopt
        return LeftoverTransition.Hold
    }

    fun generationMovedPast(seen: Long?): Boolean = leftoverTransition(seen) == LeftoverTransition.Retire

    suspend fun adoptLoadedSessions(
        sessions: List<LegacyPeriodPaymentSession>,
        creation: ExpenseManualCreation,
        bind: Boolean,
        capture: (LegacyPeriodPaymentSession) -> Unit,
    ): List<LegacyPeriodPaymentSession> {
        val bound = binding ?: return sessions
        val generation = occurrenceRowVersion ?: return sessions
        val remaining = mutableListOf<LegacyPeriodPaymentSession>()
        for (session in sessions) {
            if (!matchesLoadedSession(session)) {
                remaining += session
                continue
            }
            if (!bind) {
                capture(session)
                continue
            }
            when (creation.adoptOrigin(bound, session.clientRef, session.seriesPublicId, session.period, generation)) {
                RecurringPaymentOriginAdopt.Bound -> capture(session)
                RecurringPaymentOriginAdopt.Conflict -> remaining += session
                RecurringPaymentOriginAdopt.Missing ->
                    if (session.admitted || session.toRecurringPaymentTaskOrNull() == null) remaining += session
                    else capture(session)
            }
        }
        return remaining
    }
}

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
