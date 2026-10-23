package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.RecognitionFieldCandidate
import com.ticketbox.domain.model.RecognitionTime
import com.ticketbox.domain.model.RecognitionTimeCandidate

internal data class RecognizedEventDraft(
    val label: String,
    val fields: List<RecognitionFieldCandidate>,
    val time: RecognitionTimeCandidate?,
)

internal fun recognizedEventDrafts(fields: List<RecognitionFieldCandidate>, time: RecognitionTime?): List<RecognizedEventDraft> =
    fields.filter { it.eventId != null && it.eventSelected && it.canApply }
        .groupBy { Triple(it.source, it.evidencePublicId, it.eventId) }
        .mapNotNull { (origin, members) ->
            val times = time?.candidates.orEmpty().filter {
                Triple(it.source, it.evidencePublicId, it.eventId) == origin && it.eventSelected && it.canApply && !it.requiresYear
            }
            if (members.distinctBy { it.field }.size != members.size || times.size > 1 || members.size + times.size < 2) null
            else RecognizedEventDraft(members.first().label.substringBefore(" · "), members, times.singleOrNull())
        }

@Composable
internal fun RecognizedEventDrafts(fields: List<RecognitionFieldCandidate>, time: RecognitionTime?, enabled: Boolean,
    onField: (RecognitionFieldCandidate) -> Unit, onTime: (RecognitionTimeCandidate) -> Unit) {
    Column {
        recognizedEventDrafts(fields, time).forEach { draft ->
            val names = draft.fields.map { stringResource(if (it.field == "amount_cents")
                R.string.recognition_event_amount else R.string.recognition_event_merchant) } +
                if (draft.time != null) listOf(stringResource(R.string.recognition_event_time)) else emptyList()
            TextButton(enabled = enabled, onClick = {
                draft.fields.forEach { onField(it.copy(selectionIntent = "bookkeeping")) }
                draft.time?.let(onTime)
            }) { Text(stringResource(R.string.recognition_event_use, draft.label, names.joinToString("、"))) }
        }
    }
}
