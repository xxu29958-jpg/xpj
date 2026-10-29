package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.domain.model.OriginalTextFeedback

private val originalFeedbackAdapter = Moshi.Builder().build().adapter<List<OriginalTextFeedback>>(
    Types.newParameterizedType(List::class.java, OriginalTextFeedback::class.java),
)

internal fun readOriginalFeedback(raw: String?): List<OriginalTextFeedback> =
    raw?.let { originalFeedbackAdapter.fromJson(it) }.orEmpty()

internal fun updateOriginalFeedback(raw: String?, field: String, feedback: OriginalTextFeedback?): String? =
    (readOriginalFeedback(raw).filter { it.field != field } + listOfNotNull(feedback))
        .takeIf { it.isNotEmpty() }?.let(originalFeedbackAdapter::toJson)

internal fun OriginalTextFeedback.readyForSave(expectedHash: String?): Boolean =
    imageSha256 == expectedHash && imageSha256.length == 64 && width > 0 && height > 0 &&
        (issue in listOf("unreadable", "cropped", "absent") || verbatimText.isNotBlank())

internal data class OriginalFeedbackFieldState(val field: String, val image: OcrSourceImageState,
    val value: OriginalTextFeedback?, val enabled: Boolean) {
    fun draft(): OriginalTextFeedback {
        val size = image.image?.takeIf { it.originalSha256 == image.expectedHash }?.let(::sourceSize)
        val initial = value ?: OriginalTextFeedback(field, image.expectedHash.orEmpty(), 0, 0,
            role = when (field) { "amount_cents" -> "payment"; "expense_time" -> "transaction"; else -> field })
        return if (size == null || initial.width > 0 || initial.imageSha256 != image.expectedHash) initial else initial.copy(
            width = size.width.toInt(), height = size.height.toInt())
    }
}

@Composable
internal fun OriginalTextFeedbackField(state: OriginalFeedbackFieldState,
    onChange: (OriginalTextFeedback?) -> Unit, onLoadImage: () -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(state.value != null) }
    var positionOpen by rememberSaveable { mutableStateOf(false) }
    val draft = state.draft()
    LaunchedEffect(state.image.image, state.value) {
        if (state.value != null && draft != state.value) onChange(draft)
    }
    TextButton(enabled = state.enabled, onClick = {
        expanded = !expanded
        if (expanded && state.image.image == null && !state.image.loading) onLoadImage()
    }) { Text(stringResource(if (state.value == null) R.string.original_feedback_open else R.string.original_feedback_pending)) }
    if (expanded) Column {
        Text(stringResource(R.string.original_feedback_help), style = MaterialTheme.typography.bodySmall)
        OriginalFeedbackInputs(draft, state.enabled, onChange)
        Text(stringResource(originalFeedbackLocationLabel(draft.locationState)))
        TextButton(enabled = state.enabled, onClick = {
            positionOpen = true
            if (state.image.image == null && !state.image.loading) onLoadImage()
        }) { Text(stringResource(R.string.original_feedback_locate)) }
        if (draft.box != null) Row(Modifier.toggleable(draft.locationState == "verified_region", enabled = state.enabled,
            role = Role.Checkbox, onValueChange = { onChange(draft.copy(locationState = if (it) "verified_region" else "suggested_region")) })) {
            Checkbox(checked = draft.locationState == "verified_region", enabled = state.enabled, onCheckedChange = null)
            Text(stringResource(R.string.original_feedback_region_check))
        }
        TextButton(enabled = state.enabled, onClick = { onChange(null); expanded = false }) {
            Text(stringResource(R.string.original_feedback_remove))
        }
    }
    if (positionOpen) OriginalFeedbackPosition(state.image, draft, onApply = { onChange(it); positionOpen = false },
        onDismiss = { positionOpen = false })
}

private fun originalFeedbackLocationLabel(state: String): Int = when (state) {
    "coarse_point" -> R.string.original_feedback_point
    "suggested_region" -> R.string.original_feedback_region_pending
    "verified_region" -> R.string.original_feedback_region_verified
    else -> R.string.original_feedback_unlocated
}

@Composable
private fun OriginalFeedbackInputs(value: OriginalTextFeedback, enabled: Boolean, onChange: (OriginalTextFeedback?) -> Unit) {
    val noText = value.issue in listOf("unreadable", "cropped", "absent")
    FlowRow {
        for ((issue, label) in listOf("transcription" to R.string.original_feedback_wrong,
            "missing" to R.string.original_feedback_missing, "unreadable" to R.string.original_feedback_unreadable,
            "cropped" to R.string.original_feedback_cropped, "absent" to R.string.original_feedback_absent)) {
            TextButton(enabled = enabled && issue != value.issue, onClick = {
                onChange(value.copy(issue = issue, verbatimText = if (issue in listOf("unreadable", "cropped", "absent")) "" else value.verbatimText,
                    textVerified = false))
            }) { Text(stringResource(label)) }
        }
    }
    if (!noText) {
        OutlinedTextField(value = value.verbatimText, enabled = enabled, label = { Text(stringResource(R.string.original_feedback_text)) },
            onValueChange = { onChange(value.copy(verbatimText = it, textVerified = false)) })
        Row(Modifier.toggleable(value.textVerified, enabled = enabled && value.verbatimText.isNotBlank(), role = Role.Checkbox,
            onValueChange = { onChange(value.copy(textVerified = it)) })) {
            Checkbox(checked = value.textVerified, enabled = enabled && value.verbatimText.isNotBlank(), onCheckedChange = null)
            Text(stringResource(R.string.original_feedback_text_check))
        }
    }
    val roles = when (value.field) {
        "amount_cents" -> listOf("payment" to R.string.original_feedback_payment, "original_price" to R.string.original_feedback_price,
            "discount" to R.string.original_feedback_discount)
        "expense_time" -> listOf("transaction" to R.string.original_feedback_transaction_time,
            "order" to R.string.original_feedback_order_time, "capture" to R.string.original_feedback_capture_time)
        else -> emptyList()
    }
    FlowRow { for ((role, label) in roles) TextButton(enabled = enabled && value.role != role,
        onClick = { onChange(value.copy(role = role)) }) { Text(stringResource(label)) } }
}

@Composable
private fun OriginalFeedbackPosition(image: OcrSourceImageState, value: OriginalTextFeedback,
    onApply: (OriginalTextFeedback) -> Unit, onDismiss: () -> Unit) {
    var selected by rememberSaveable { mutableStateOf((value.box ?: value.point).orEmpty().map(Float::toInt).toIntArray()) }
    val ready = image.image != null && image.image.originalSha256 == image.expectedHash && sourceSize(image.image) != null
    Dialog(onDismissRequest = onDismiss) {
        Surface(shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
                Text(stringResource(R.string.original_feedback_locate), style = MaterialTheme.typography.titleLarge)
                Text(stringResource(R.string.original_feedback_location_help))
                if (ready) RegionSelectionImage(requireNotNull(image.image), selected, true) { selected = it }
                else Text(stringResource(if (image.loading) R.string.expense_edit_large_image_loading else R.string.expense_edit_large_image_failed))
                FlowRow {
                    TextButton(onClick = onDismiss) { Text(stringResource(R.string.ocr_region_cancel)) }
                    TextButton(onClick = { selected = intArrayOf() }) { Text(stringResource(R.string.original_feedback_skip_location)) }
                    TextButton(enabled = ready, onClick = {
                        onApply(value.copy(locationState = when (selected.size) { 2 -> "coarse_point"; 4 -> "suggested_region"; else -> "unlocated" },
                            point = selected.takeIf { it.size == 2 }?.map(Int::toFloat),
                            box = selected.takeIf { it.size == 4 }?.map(Int::toFloat)))
                    }) { Text(stringResource(R.string.original_feedback_use_location)) }
                }
            }
        }
    }
}
