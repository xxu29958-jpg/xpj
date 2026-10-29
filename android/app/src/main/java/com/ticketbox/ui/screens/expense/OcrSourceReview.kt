package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.ticketbox.R
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RecognitionSourceLocation

internal data class OcrSourceEntry(val id: String, val label: String, val text: String, val location: RecognitionSourceLocation)
internal data class OcrSourceImageState(val image: ProtectedImage?, val expectedHash: String?, val loading: Boolean)

@Composable
internal fun OcrSourceReview(state: OcrSourceImageState, entries: List<OcrSourceEntry>,
    selectedId: String, onSelect: (String?) -> Unit) {
    val image = state.image
    val entry = entries.firstOrNull { it.id == selectedId }
    val location = entry?.location
    val size = image?.let(::sourceSize)
    val ready = location != null && location.imageSha256 == state.expectedHash && image?.originalSha256 == state.expectedHash &&
        size?.width == location.width.toFloat() && size.height == location.height.toFloat() &&
        location.coordinateSpace == "exif-transposed-pixels"
    Dialog(onDismissRequest = { onSelect(null) }) {
        Surface(shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(entry?.label ?: stringResource(R.string.recognition_source_open), style = MaterialTheme.typography.titleLarge)
                Text(entry?.text.orEmpty())
                if (ready) RegionSelectionImage(requireNotNull(image), intArrayOf(), true, location) {}
                else Text(stringResource(when {
                    state.loading -> R.string.expense_edit_large_image_loading
                    image == null -> R.string.expense_edit_large_image_failed
                    else -> R.string.recognition_source_unavailable
                }))
                Text(stringResource(R.string.recognition_source_help))
                FlowRow {
                    TextButton(onClick = { onSelect(null) }) { Text(stringResource(R.string.ocr_region_cancel)) }
                    val index = entries.indexOfFirst { it.id == selectedId }
                    TextButton(enabled = index > 0, onClick = { onSelect(entries[index - 1].id) }) {
                        Text(stringResource(R.string.recognition_source_previous))
                    }
                    TextButton(enabled = index >= 0 && index < entries.lastIndex, onClick = { onSelect(entries[index + 1].id) }) {
                        Text(stringResource(R.string.recognition_source_next))
                    }
                }
            }
        }
    }
}
