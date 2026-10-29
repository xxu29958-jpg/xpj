package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.clickable
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.domain.model.RecognitionFieldCandidate
import com.ticketbox.domain.model.RecognitionFieldChoice
import com.ticketbox.ui.components.AppPaperCard

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
        Text(stringResource(if (candidates.first().field == "amount_cents") R.string.recognition_fields_amount_title
            else R.string.recognition_fields_merchant_title), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.recognition_fields_help), style = MaterialTheme.typography.bodySmall)
        Text(stringResource(R.string.recognition_fields_correction_help), style = MaterialTheme.typography.bodySmall)
        candidates.forEach { candidate ->
            RecognitionCandidateCard(enabled, if (candidate.canApply) ({ onChoose(candidate) }) else null) {
                Text(candidate.label, style = MaterialTheme.typography.titleSmall)
                Text(candidate.originalText, style = MaterialTheme.typography.bodyMedium)
                Text(candidate.explanation, style = MaterialTheme.typography.bodySmall)
                if (candidate.canApply) Text(stringResource(if (candidate.field == "amount_cents")
                    R.string.recognition_fields_amount else R.string.recognition_fields_merchant), color = MaterialTheme.colorScheme.primary)
            }
            if (candidate.sourceLocation != null) TextButton(onClick = { onSource(candidate.id) }) {
                Text(stringResource(R.string.recognition_source_open))
            }
            if (candidate.canApply) TextButton(enabled = enabled, onClick = { onCorrect(candidate) }) {
                Text(stringResource(if (candidate.field == "amount_cents") R.string.recognition_fields_correct_amount else R.string.recognition_fields_correct_merchant))
            }
        }
    }
}

@Composable
internal fun RecognitionCandidateCard(enabled: Boolean, onClick: (() -> Unit)?, content: @Composable ColumnScope.() -> Unit) {
    AppPaperCard(Modifier.padding(vertical = 4.dp)) {
        val target = Modifier.fillMaxWidth().heightIn(min = 48.dp)
        Column((if (onClick == null) target else target.clickable(enabled = enabled, role = Role.Button, onClick = onClick))
            .padding(12.dp), content = content)
    }
}
