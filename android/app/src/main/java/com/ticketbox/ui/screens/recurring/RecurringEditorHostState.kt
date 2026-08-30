package com.ticketbox.ui.screens.recurring

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem

/** The one presentation owner for an open recurring editor and its OCC-bound draft. */
internal sealed interface RecurringEditorTarget {
    data object Create : RecurringEditorTarget
    data class Edit(val publicId: String) : RecurringEditorTarget
}

internal data class RecurringEditorState(
    val target: RecurringEditorTarget,
    val session: RecurringEditorSession,
)

@Stable
internal class RecurringEditorHostState internal constructor(
    initialEditor: RecurringEditorState? = null,
) {
    var editor by mutableStateOf(initialEditor)
        private set

    fun openCreate(currency: CurrencyCode) {
        editor = RecurringEditorState(
            target = RecurringEditorTarget.Create,
            session = newRecurringEditorSession(baseline = null, currency = currency),
        )
    }

    fun openEdit(item: RecurringItem, currency: CurrencyCode) {
        require(item.publicId.isNotBlank()) { "recurring editor target must have a public id" }
        editor = RecurringEditorState(
            target = RecurringEditorTarget.Edit(item.publicId),
            session = newRecurringEditorSession(baseline = item, currency = currency),
        )
    }

    fun dismiss() {
        editor = null
    }
}

/**
 * Saved-instance-state restoration is accepted only by the same ViewModel runtime
 * and logical-ledger editor epoch.
 * A new process gets a new runtime id and starts without an orphaned in-flight attempt;
 * durable process-death publication ownership remains a separate outbox slice.
 */
@Composable
internal fun rememberRecurringEditorHostState(
    editorEpoch: Long,
    runtimeId: String,
): RecurringEditorHostState = rememberSaveable(
    editorEpoch,
    runtimeId,
    saver = recurringEditorHostStateSaver(editorEpoch, runtimeId),
) {
    RecurringEditorHostState()
}

private fun recurringEditorHostStateSaver(editorEpoch: Long, runtimeId: String) =
    listSaver<RecurringEditorHostState, String>(
        save = { host ->
            buildList {
                add(runtimeId)
                add(editorEpoch.toString())
                val editor = host.editor
                when (val target = editor?.target) {
                    null -> add(TARGET_NONE)
                    RecurringEditorTarget.Create -> {
                        add(TARGET_CREATE)
                        addSession(checkNotNull(editor).session)
                    }
                    is RecurringEditorTarget.Edit -> {
                        add(TARGET_EDIT)
                        add(target.publicId)
                        addSession(checkNotNull(editor).session)
                    }
                }
            }
        },
        restore = { saved ->
            runCatching {
                val values = saved.iterator()
                if (values.next() != runtimeId) return@runCatching RecurringEditorHostState()
                if (values.next().toLong() != editorEpoch) return@runCatching RecurringEditorHostState()
                when (val kind = values.next()) {
                    TARGET_NONE -> RecurringEditorHostState()
                    TARGET_CREATE -> {
                        val session = values.readSession()
                        check(session.editing == null)
                        RecurringEditorHostState(
                            RecurringEditorState(RecurringEditorTarget.Create, session),
                        )
                    }
                    TARGET_EDIT -> {
                        val publicId = values.next()
                        val session = values.readSession()
                        check(session.editing?.publicId == publicId)
                        RecurringEditorHostState(
                            RecurringEditorState(RecurringEditorTarget.Edit(publicId), session),
                        )
                    }
                    else -> error("unknown recurring editor target: $kind")
                }
            }.getOrElse { RecurringEditorHostState() }
        },
    )

private fun MutableList<String>.addSession(session: RecurringEditorSession) {
    val baseline = session.editing
    add(if (baseline == null) VALUE_ABSENT else VALUE_PRESENT)
    baseline?.let(::addRecurringItem)
    add(session.merchant)
    add(session.amountText)
    addNullable(session.dateIso)
    addBoolean(session.dateTouched)
    addBoolean(session.showDatePicker)
    addNullable(session.submitUi.attemptId?.toString())
    addBoolean(session.submitUi.awaiting)
    addNullable(session.submitUi.error)
    addNullable(session.rebaseUi?.attemptId?.toString())
    add(
        session.rebaseUi?.overlappingFields
            ?.sortedBy(RecurringEditField::ordinal)
            ?.joinToString(",", transform = RecurringEditField::name)
            .orEmpty(),
    )
}

private fun Iterator<String>.readSession(): RecurringEditorSession {
    val baseline = when (next()) {
        VALUE_ABSENT -> null
        VALUE_PRESENT -> readRecurringItem()
        else -> error("invalid recurring editor baseline marker")
    }
    val draft = RecurringDraftStates(
        editing = mutableStateOf(baseline),
        merchant = mutableStateOf(next()),
        amountText = mutableStateOf(next()),
        dateIso = mutableStateOf(next().decodeNullable()),
        dateTouched = mutableStateOf(next().decodeBoolean()),
    )
    val showDatePicker = next().decodeBoolean()
    val submitAttempt = next().decodeNullable()?.toLong()
    val submitUi = RecurringSubmitUi(
        attemptId = submitAttempt,
        awaiting = next().decodeBoolean(),
        error = next().decodeNullable(),
    )
    val rebaseAttempt = next().decodeNullable()?.toLong()
    val overlappingFields = next()
        .split(',')
        .filter(String::isNotBlank)
        .mapTo(linkedSetOf()) { name -> RecurringEditField.valueOf(name) }
    val interaction = RecurringInteractionStates(
        showDatePicker = mutableStateOf(showDatePicker),
        submitUi = mutableStateOf(submitUi),
        rebaseUi = mutableStateOf(
            rebaseAttempt?.let { RecurringRebaseUi(it, overlappingFields) },
        ),
    )
    return RecurringEditorSession(draft, interaction)
}

private fun MutableList<String>.addRecurringItem(item: RecurringItem) {
    add(item.publicId)
    add(item.ledgerId)
    add(item.merchant)
    add(item.merchantKey)
    add(item.frequency)
    add(item.baselineAmountCents.toString())
    add(item.lastAmountCents.toString())
    add(item.occurrenceCount.toString())
    addNullable(item.lastSeenAt)
    addNullable(item.nextExpectedDate)
    add(item.status)
    addNullable(item.confidence)
    add(item.source)
    add(item.anomalyStatus)
    addNullable(item.currentMonthAmountCents?.toString())
    addNullable(item.historicalAverageAmountCents?.toString())
    addNullable(item.amountDeltaPercent?.toString())
    add(item.createdAt)
    add(item.updatedAt)
    add(item.rowVersion.toString())
    addNullable(item.pausedAt)
    addNullable(item.archivedAt)
}

private fun Iterator<String>.readRecurringItem(): RecurringItem = RecurringItem(
    publicId = next(),
    ledgerId = next(),
    merchant = next(),
    merchantKey = next(),
    frequency = next(),
    baselineAmountCents = next().toLong(),
    lastAmountCents = next().toLong(),
    occurrenceCount = next().toInt(),
    lastSeenAt = next().decodeNullable(),
    nextExpectedDate = next().decodeNullable(),
    status = next(),
    confidence = next().decodeNullable(),
    source = next(),
    anomalyStatus = next(),
    currentMonthAmountCents = next().decodeNullable()?.toLong(),
    historicalAverageAmountCents = next().decodeNullable()?.toLong(),
    amountDeltaPercent = next().decodeNullable()?.toInt(),
    createdAt = next(),
    updatedAt = next(),
    rowVersion = next().toLong(),
    pausedAt = next().decodeNullable(),
    archivedAt = next().decodeNullable(),
)

private fun MutableList<String>.addNullable(value: String?) {
    add(if (value == null) VALUE_ABSENT else VALUE_PRESENT + value)
}

private fun String.decodeNullable(): String? = when {
    this == VALUE_ABSENT -> null
    startsWith(VALUE_PRESENT) -> drop(1)
    else -> error("invalid nullable recurring editor value")
}

private fun MutableList<String>.addBoolean(value: Boolean) {
    add(if (value) VALUE_TRUE else VALUE_FALSE)
}

private fun String.decodeBoolean(): Boolean = when (this) {
    VALUE_TRUE -> true
    VALUE_FALSE -> false
    else -> error("invalid recurring editor boolean")
}

private const val TARGET_NONE = "none"
private const val TARGET_CREATE = "create"
private const val TARGET_EDIT = "edit"
private const val VALUE_ABSENT = "0"
private const val VALUE_PRESENT = "1"
private const val VALUE_FALSE = "0"
private const val VALUE_TRUE = "1"
