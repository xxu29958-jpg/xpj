package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.clickable
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecognitionFieldCandidate
import com.ticketbox.domain.model.RecognitionFieldChoice
import com.ticketbox.presentation.parseMinorAmount
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppSpacing

private val fieldChoiceAdapter = Moshi.Builder().build().adapter<List<RecognitionFieldChoice>>(
    Types.newParameterizedType(List::class.java, RecognitionFieldChoice::class.java),
)

internal fun readFieldChoices(raw: String?): List<RecognitionFieldChoice> =
    raw?.let { runCatching { fieldChoiceAdapter.fromJson(it) }.getOrNull() }.orEmpty()

internal fun updateFieldChoice(raw: String?, field: String, choice: RecognitionFieldChoice? = null): String? {
    val values = readFieldChoices(raw).filter { it.field != field } + listOfNotNull(choice)
    return values.takeIf { it.isNotEmpty() }?.let(fieldChoiceAdapter::toJson)
}

/** What the last tap on a reading, or an edit after it, did to this field's recorded choice. */
internal enum class FieldChoiceStatus { Applied, Recorded, Empty, Unchanged, OtherCurrency, SourceUnavailable, Cancelled }

/**
 * Same rule as the Web form and the backend's learning qualification: a correction is only worth
 * recording when the field holds a value that differs from the parser's own reading, in that reading's
 * currency. A recalled suggestion replaces `value`, never the source reading, so only the latter counts.
 */
internal fun correctionStatus(candidate: RecognitionFieldCandidate, amountText: String, currency: CurrencyCode,
    merchant: String): FieldChoiceStatus {
    val reading = candidate.sourceReadingValue
    val input = if (candidate.field == "amount_cents") amountText else merchant
    return when {
        input.isBlank() -> FieldChoiceStatus.Empty
        reading == null -> FieldChoiceStatus.SourceUnavailable
        candidate.field != "amount_cents" -> if (merchant.trim() == reading.trim()) FieldChoiceStatus.Unchanged
            else FieldChoiceStatus.Recorded
        CurrencyCode.fromStorageKeyOrNull(candidate.currencyCode) != currency -> FieldChoiceStatus.OtherCurrency
        parseMinorAmount(amountText, currency) == reading.toLongOrNull() -> FieldChoiceStatus.Unchanged
        else -> FieldChoiceStatus.Recorded
    }
}

internal data class RecognizedFieldCandidatesState(
    val candidates: List<RecognitionFieldCandidate>,
    val enabled: Boolean,
    val status: FieldChoiceStatus? = null,
    // The amount input gaining focus opens its readings, as focusing the Web field does.
    val openRequested: Boolean = false,
)

internal data class RecognizedFieldCandidatesActions(
    val onChoose: (RecognitionFieldCandidate) -> Unit,
    val onSource: (String) -> Unit,
    val onCorrect: (RecognitionFieldCandidate) -> Unit,
)

@Composable
internal fun RecognizedFieldCandidates(state: RecognizedFieldCandidatesState, actions: RecognizedFieldCandidatesActions) {
    val candidates = state.candidates
    if (candidates.isEmpty()) return
    val amount = candidates.first().field == "amount_cents"
    // Folded by default; a reading the user's own earlier correction suggests starts open.
    var expanded by rememberSaveable(candidates.first().field) {
        mutableStateOf(candidates.any { it.selectionIntent == "bookkeeping" })
    }
    LaunchedEffect(state.openRequested) { if (state.openRequested) expanded = true }
    Column {
        RecognizedFieldHeader(stringResource(if (amount) R.string.recognition_fields_amount_title
            else R.string.recognition_fields_merchant_title), candidates.size, expanded) { expanded = !expanded }
        if (expanded) {
            Text(stringResource(R.string.recognition_fields_help), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.recognition_fields_correction_help), style = MaterialTheme.typography.bodySmall)
            candidates.forEach { candidate -> RecognizedFieldCandidate(candidate, state.enabled, actions) }
        }
        state.status?.let { status ->
            Text(fieldChoiceStatusText(status, amount), style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(vertical = 4.dp).semantics { liveRegion = LiveRegionMode.Polite })
        }
    }
}

@Composable
private fun RecognizedFieldHeader(title: String, count: Int, expanded: Boolean, onToggle: () -> Unit) {
    val state = stringResource(if (expanded) R.string.expense_edit_details_row_expanded else R.string.expense_edit_details_row_collapsed)
    Row(
        modifier = Modifier.fillMaxWidth().defaultMinSize(minHeight = AppSpacing.controlMinHeight)
            .clickable(role = Role.Button, onClick = onToggle).semantics { stateDescription = state },
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(stringResource(R.string.recognition_fields_count, count), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Icon(ImageVector.vectorResource(if (expanded) R.drawable.ic_lucide_chevron_up else R.drawable.ic_lucide_chevron_down),
            contentDescription = null, modifier = Modifier.size(AppIconSize.compact))
    }
}

@Composable
private fun RecognizedFieldCandidate(candidate: RecognitionFieldCandidate, enabled: Boolean, actions: RecognizedFieldCandidatesActions) {
    val amount = candidate.field == "amount_cents"
    RecognitionCandidateCard(enabled, if (candidate.canApply) ({ actions.onChoose(candidate) }) else null) {
        Text(candidate.label, style = MaterialTheme.typography.titleSmall)
        Text(candidate.originalText, style = MaterialTheme.typography.bodyMedium)
        Text(candidate.explanation, style = MaterialTheme.typography.bodySmall)
        if (candidate.canApply) Text(stringResource(if (amount) R.string.recognition_fields_amount
            else R.string.recognition_fields_merchant), color = MaterialTheme.colorScheme.primary)
    }
    if (candidate.sourceLocation != null) TextButton(onClick = { actions.onSource(candidate.id) }) {
        Text(stringResource(R.string.recognition_source_open))
    }
    if (candidate.canApply) TextButton(enabled = enabled, onClick = { actions.onCorrect(candidate) }) {
        Text(stringResource(if (amount) R.string.recognition_fields_correct_amount else R.string.recognition_fields_correct_merchant))
    }
}

@Composable
private fun fieldChoiceStatusText(status: FieldChoiceStatus, amount: Boolean): String {
    val noun = stringResource(if (amount) R.string.recognition_fields_noun_amount else R.string.recognition_fields_noun_merchant)
    return when (status) {
        FieldChoiceStatus.Applied -> stringResource(R.string.recognition_fields_status_applied)
        FieldChoiceStatus.Recorded -> stringResource(R.string.recognition_fields_status_recorded)
        FieldChoiceStatus.Empty -> stringResource(R.string.recognition_fields_status_empty, noun)
        FieldChoiceStatus.Unchanged -> stringResource(R.string.recognition_fields_status_unchanged, noun)
        FieldChoiceStatus.OtherCurrency -> stringResource(R.string.recognition_fields_status_other_currency)
        FieldChoiceStatus.SourceUnavailable -> stringResource(R.string.recognition_fields_status_source_unavailable)
        FieldChoiceStatus.Cancelled -> stringResource(R.string.recognition_fields_status_cancelled, noun)
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
