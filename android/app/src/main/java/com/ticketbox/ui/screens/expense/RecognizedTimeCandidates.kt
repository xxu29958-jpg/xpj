package com.ticketbox.ui.screens.expense

import com.ticketbox.viewmodel.ExpenseTimeForm
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.RecognitionTime
import com.ticketbox.domain.model.RecognitionTimeCandidate
import java.time.ZoneOffset
import java.time.LocalDate
import java.time.LocalTime

@Composable
internal fun RecognizedTimeCandidates(
    evidence: RecognitionTime?, form: ExpenseTimeForm, onChange: (ExpenseTimeForm) -> Unit, enabled: Boolean,
    onSource: (String) -> Unit = {},
) {
    RecognizedTimeChoices(evidence, enabled = enabled, onSource = onSource) { candidate -> onChange(form.withRecognizedTime(candidate)) }
}

@Composable
internal fun RecognizedTimeChoices(evidence: RecognitionTime?, enabled: Boolean, dateOnly: Boolean = false,
    onSource: ((String) -> Unit)? = null,
    onChoose: ((RecognitionTimeCandidate) -> Unit)? = null) {
    if (evidence == null) return
    Column {
        Text(stringResource(R.string.recognition_time_title), style = MaterialTheme.typography.titleSmall)
        if (onChoose != null) Text(stringResource(R.string.recognition_time_help), style = MaterialTheme.typography.bodySmall)
        if (evidence.status == "ambiguous") Text(stringResource(R.string.recognition_time_conflict))
        if (evidence.status == "incomplete") Text(stringResource(R.string.recognition_time_incomplete))
        if (dateOnly) Text(stringResource(R.string.recognition_time_date_help), style = MaterialTheme.typography.bodySmall)
        evidence.candidates.forEach { candidate ->
            RecognizedTimeRow(candidate, enabled, dateOnly, onSource, onChoose)
        }
    }
}

@Composable
private fun RecognizedTimeRow(candidate: RecognitionTimeCandidate, enabled: Boolean, dateOnly: Boolean,
    onSource: ((String) -> Unit)?,
    onChoose: ((RecognitionTimeCandidate) -> Unit)?) {
    var year by rememberSaveable(candidate.id) { mutableStateOf("") }
    val choice = if (candidate.requiresYear) candidate.withYear(year) else candidate.takeIf { it.canApply }
    RecognitionCandidateCard(enabled && choice != null, onChoose?.let { { choice?.let(it) } }) {
        Text("${candidate.label} · ${candidate.localValue}", style = MaterialTheme.typography.titleSmall)
        Text(candidate.originalText, style = MaterialTheme.typography.bodyMedium)
        Text(candidate.explanation, style = MaterialTheme.typography.bodySmall)
        if (onChoose != null && (candidate.canApply || candidate.requiresYear)) Text(stringResource(
            if (dateOnly) R.string.recognition_time_use_date else R.string.recognition_time_use), color = MaterialTheme.colorScheme.primary)
    }
    if (candidate.sourceLocation != null && onSource != null) TextButton(onClick = { onSource(candidate.id) }) {
        Text(stringResource(R.string.recognition_source_open))
    }
    if (onChoose == null) return
    if (candidate.requiresYear) OutlinedTextField(value = year, onValueChange = {
        year = it.filter(Char::isDigit).take(4)
    }, enabled = enabled, label = { Text(stringResource(R.string.recognition_time_year)) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true)
}

internal fun RecognitionTimeCandidate.withYear(year: String): RecognitionTimeCandidate? {
    if (!requiresYear || !year.matches(Regex("[1-9][0-9]{3}"))) return null
    return runCatching {
        val date = LocalDate.of(year.toInt(), components.getValue("month"), components.getValue("day"))
        val value = if (precision == "date_only") date.toString() else {
            val time = LocalTime.of(components.getValue("hour"), components.getValue("minute"), components.getValue("second"))
            "$date" + "T" + if (precision == "second") time.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss"))
                else time.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
        }
        copy(localValue = value, canApply = true)
    }.getOrNull()
}

internal fun ExpenseTimeForm.withEventTime(candidate: RecognitionTimeCandidate): ExpenseTimeForm {
    val chosen = withRecognizedTime(candidate)
    return chosen.copy(recognitionChoice = chosen.recognitionChoice?.copy(intent = "bookkeeping"))
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
        com.ticketbox.domain.model.RecognitionTimeChoice(candidate.evidencePublicId, candidate.id, candidate.parserVersion, candidate.source,
            intent = if (candidate.requiresYear) "original_correction" else "candidate")
        else null,
)
