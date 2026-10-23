package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.RecognitionTime
import com.ticketbox.domain.model.RecognitionTimeCandidate
import java.time.ZoneOffset

@Composable
internal fun RecognizedTimeCandidates(
    evidence: RecognitionTime?, form: ExpenseTimeForm, onChange: (ExpenseTimeForm) -> Unit, enabled: Boolean,
) {
    RecognizedTimeChoices(evidence, enabled = enabled) { candidate -> onChange(form.withRecognizedTime(candidate)) }
}

@Composable
internal fun RecognizedTimeChoices(evidence: RecognitionTime?, enabled: Boolean, dateOnly: Boolean = false,
    onChoose: ((RecognitionTimeCandidate) -> Unit)? = null) {
    if (evidence == null) return
    Column {
        Text(stringResource(R.string.recognition_time_title), style = MaterialTheme.typography.titleSmall)
        if (onChoose != null) Text(stringResource(R.string.recognition_time_help), style = MaterialTheme.typography.bodySmall)
        if (evidence.status == "ambiguous") Text(stringResource(R.string.recognition_time_conflict))
        if (evidence.status == "incomplete") Text(stringResource(R.string.recognition_time_incomplete))
        if (dateOnly) Text(stringResource(R.string.recognition_time_date_help), style = MaterialTheme.typography.bodySmall)
        evidence.candidates.forEach { candidate ->
            Text("${candidate.label} · ${candidate.localValue}")
            Text(candidate.originalText, style = MaterialTheme.typography.bodySmall)
            Text(candidate.explanation, style = MaterialTheme.typography.bodySmall)
            if (candidate.canApply && onChoose != null) TextButton(enabled = enabled, onClick = {
                onChoose(candidate)
            }) { Text(stringResource(if (dateOnly) R.string.recognition_time_use_date else R.string.recognition_time_use)) }
        }
    }
}

internal fun ExpenseTimeForm.withRecognizedTime(candidate: RecognitionTimeCandidate): ExpenseTimeForm = copy(
    precision = if (candidate.precision == "date_only") "date_only" else "instant",
    date = candidate.localValue.substringBefore('T'),
    time = candidate.localValue.substringAfter('T', ""),
    sourceZone = candidate.sourceTimezone ?: candidate.sourceUtcOffsetSeconds?.let { ZoneOffset.ofTotalSeconds(it).id }
        ?: sourceZone,
    offsetSeconds = candidate.sourceUtcOffsetSeconds,
    originalInstant = null,
    changed = true,
    recognitionChoice = if (candidate.evidencePublicId != null && candidate.parserVersion != null && candidate.source != null)
        com.ticketbox.domain.model.RecognitionTimeChoice(candidate.evidencePublicId, candidate.id, candidate.parserVersion, candidate.source)
        else null,
)
