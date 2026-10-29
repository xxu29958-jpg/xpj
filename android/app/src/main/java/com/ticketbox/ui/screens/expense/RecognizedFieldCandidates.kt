package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.domain.model.RecognitionFieldCandidate
import com.ticketbox.domain.model.RecognitionFieldChoice

private val fieldChoiceAdapter = Moshi.Builder().build().adapter<List<RecognitionFieldChoice>>(
    Types.newParameterizedType(List::class.java, RecognitionFieldChoice::class.java),
)

internal fun readFieldChoices(raw: String?): List<RecognitionFieldChoice> =
    raw?.let { runCatching { fieldChoiceAdapter.fromJson(it) }.getOrNull() }.orEmpty()

internal fun updateFieldChoice(raw: String?, field: String, choice: RecognitionFieldChoice? = null): String? {
    val values = readFieldChoices(raw).filter { it.field != field } + listOfNotNull(choice)
    return values.takeIf { it.isNotEmpty() }?.let(fieldChoiceAdapter::toJson)
}

@Composable
internal fun RecognizedFieldCandidates(candidates: List<RecognitionFieldCandidate>, enabled: Boolean,
    onChoose: (RecognitionFieldCandidate) -> Unit, onSource: (String) -> Unit = {},
    onCorrect: (RecognitionFieldCandidate) -> Unit) {
    if (candidates.isEmpty()) return
    Column {
        Text(stringResource(R.string.recognition_fields_title), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.recognition_fields_help), style = MaterialTheme.typography.bodySmall)
        Text(stringResource(R.string.recognition_fields_correction_help), style = MaterialTheme.typography.bodySmall)
        candidates.forEach { candidate ->
            Text(candidate.label)
            Text(candidate.originalText, style = MaterialTheme.typography.bodySmall)
            Text(candidate.explanation, style = MaterialTheme.typography.bodySmall)
            if (candidate.sourceLocation != null) TextButton(onClick = { onSource(candidate.id) }) {
                Text(stringResource(R.string.recognition_source_open))
            }
            if (candidate.canApply) TextButton(enabled = enabled, onClick = { onChoose(candidate) }) {
                Text(stringResource(if (candidate.field == "amount_cents") R.string.recognition_fields_amount else R.string.recognition_fields_merchant))
            }
            if (candidate.canApply) TextButton(enabled = enabled, onClick = { onCorrect(candidate) }) {
                Text(stringResource(if (candidate.field == "amount_cents") R.string.recognition_fields_correct_amount else R.string.recognition_fields_correct_merchant))
            }
        }
    }
}
