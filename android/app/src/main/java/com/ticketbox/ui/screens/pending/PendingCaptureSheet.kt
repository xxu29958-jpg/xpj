package com.ticketbox.ui.screens.pending

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.vector.ImageVector
import coil3.compose.AsyncImage
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.MAX_UPLOAD_BATCH_ITEMS
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.ReceiptEmptyIllustration
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.PendingUiState
import com.ticketbox.viewmodel.PendingUploadOriginalUi

/** A task presentation over the launch selection and Room projection; it owns no upload state. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PendingCaptureSheet(
    state: PendingUiState,
    actions: PendingScreenChromeActions,
    onOpenExpense: (Expense) -> Unit,
    onDismiss: () -> Unit,
) {
    val selection = actions.uploadSelection
    val choosing = selection.pendingCount > 0
    val hasTask = !choosing && state.upload.originals.isNotEmpty()
    val received = hasTask && state.upload.originals.all { it.expenseId != null }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        AppSheetScaffold(
            title = stringResource(when {
                choosing || !hasTask -> R.string.pending_capture_title
                received -> R.string.pending_capture_all_received
                else -> R.string.pending_capture_processing
            }),
            subtitle = stringResource(if (choosing || !hasTask) R.string.pending_capture_description else R.string.pending_capture_continue),
            actions = { PendingCaptureActions(state, actions, onDismiss) },
        ) {
            if (choosing) {
                PendingSelectedImages(selection)
            } else if (!hasTask) {
                ReceiptEmptyIllustration()
                AppPrimaryButton(
                    text = stringResource(R.string.pending_capture_pick),
                    enabled = state.canStartUpload,
                    onClick = actions.onUploadScreenshot,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (hasTask) PendingCaptureProgress(state, actions.onOpenUploadExpense, onDismiss)
            state.message?.let { CaptureNote(it.asString()) }
            if (!choosing) PendingCaptureFeedback(state, actions, onOpenExpense, onDismiss)
            CaptureNote(stringResource(R.string.pending_capture_original_note))
        }
    }
}

@Composable
private fun PendingCaptureFeedback(state: PendingUiState, actions: PendingScreenChromeActions, onOpenExpense: (Expense) -> Unit, onDismiss: () -> Unit) {
    state.uploadMessage?.let { CaptureNote(it.asString()) }
    val target = state.items.firstOrNull { it.id == state.enrichment.feedback?.expenseId }
    PendingEnrichmentStatusBand(state.enrichment, target != null,
        onOpenFeedbackExpense = { target?.let { onDismiss(); onOpenExpense(it) } },
        onRetryObservation = actions.onRetryEnrichment)
}

@Composable
private fun PendingSelectedImages(selection: PendingUploadSelectionUiState) {
    AppSectionHeader(stringResource(R.string.pending_capture_selected, selection.pendingCount))
    if (selection.pendingCount > MAX_UPLOAD_BATCH_ITEMS) {
        CaptureNote(stringResource(R.string.pending_upload_selection_too_many, MAX_UPLOAD_BATCH_ITEMS))
    } else if (selection.accepting || selection.attempted) {
        CaptureNote(stringResource(if (selection.accepting) R.string.pending_upload_selection_saving
            else R.string.pending_upload_selection_waiting, selection.pendingCount))
    }
    selection.imageRefs.forEachIndexed { index, source ->
        AppListRow {
            // Local picker/share URIs stay with Android's grant owner; previewing does not copy or accept the file.
            Box(Modifier.size(AppAsyncImageLayout.ReceiptThumbnail.compactSize).clip(RoundedCornerShape(AppRadius.small))
                .background(MaterialTheme.colorScheme.surfaceVariant)) {
                Text(stringResource(R.string.pending_capture_preview), style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(AppSpacing.smallGap))
                AsyncImage(model = Uri.parse(source), contentDescription = stringResource(R.string.pending_capture_image, index + 1),
                    contentScale = ContentScale.Fit, modifier = Modifier.matchParentSize())
            }
            Column(Modifier.weight(1f).padding(start = AppSpacing.cardGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.pending_capture_image, index + 1), style = MaterialTheme.typography.titleMedium)
                CaptureNote(stringResource(if (selection.attempted) R.string.pending_capture_original_selection else R.string.pending_capture_not_uploaded))
                if (!selection.attempted) TextButton(onClick = { selection.onRemove(index) }, enabled = !selection.accepting) {
                    Text(stringResource(R.string.pending_capture_remove))
                }
            }
        }
    }
}

@Composable
private fun PendingCaptureProgress(state: PendingUiState, onOpenExpense: (Long) -> Unit, onDismiss: () -> Unit) {
    val originals = state.upload.originals
    val received = originals.count { it.expenseId != null }
    AppSectionHeader(stringResource(R.string.pending_capture_progress), stringResource(R.string.pending_capture_received, received, originals.size))
    LinearProgressIndicator(progress = { received.toFloat() / originals.size }, modifier = Modifier.fillMaxWidth())
    originals.forEach { original ->
        val expense = state.items.firstOrNull { it.id == original.expenseId }
        AppListRow {
            val thumbnail = original.expenseId?.let(state.thumbnails::get)
            if (thumbnail != null) AppAsyncImage(thumbnail, layout = AppAsyncImageLayout.ReceiptThumbnail)
            else SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_image_plus))
            Column(Modifier.weight(1f).padding(start = AppSpacing.cardGap), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(original.fileName ?: stringResource(R.string.pending_capture_image, original.position), style = MaterialTheme.typography.titleMedium)
                CaptureNote(stringResource(original.statusLabel()))
                original.expenseId?.let { id ->
                    TextButton(onClick = { onDismiss(); onOpenExpense(id) }) {
                        Text(stringResource(if (expense != null) R.string.pending_capture_review else R.string.pending_capture_open_original))
                    }
                }
            }
        }
    }
}

private fun PendingUploadOriginalUi.statusLabel(): Int = when {
    expenseId != null -> R.string.pending_capture_received_review
    status == PendingMutationStatus.Done -> R.string.pending_capture_unknown
    status == PendingMutationStatus.InFlight -> R.string.pending_capture_uploading
    status == PendingMutationStatus.Unknown -> R.string.pending_capture_unknown
    status == PendingMutationStatus.Failed || status == PendingMutationStatus.Conflict -> R.string.pending_capture_not_received
    else -> R.string.pending_capture_saved_local
}

@Composable
private fun PendingCaptureActions(state: PendingUiState, actions: PendingScreenChromeActions, onDismiss: () -> Unit) {
    val selection = actions.uploadSelection
    val primary = when {
        selection.pendingCount > 0 -> AppAction(
            text = if (selection.attempted) stringResource(R.string.pending_upload_selection_retry)
                else stringResource(R.string.pending_capture_submit, selection.pendingCount),
            onClick = selection.onRetry, enabled = selection.canRetry && state.canStartUpload,
        )
        state.canRetryUpload -> AppAction(stringResource(R.string.pending_upload_retry_action), actions.onRetryCapacityUpload)
        else -> null
    }
    if (primary != null) AppActionRow(primary, secondary = AppAction(stringResource(R.string.pending_capture_back), onDismiss))
    else TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pending_capture_back)) }
    if (selection.pendingCount > 0) {
        TextButton(onClick = selection.onStop, enabled = !selection.accepting) { Text(stringResource(R.string.pending_upload_selection_stop)) }
    } else if (state.canStopUpload) {
        TextButton(onClick = actions.onDiscardCapacityUpload) { Text(stringResource(R.string.pending_upload_stop_action)) }
    }
}

@Composable
private fun CaptureNote(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}
