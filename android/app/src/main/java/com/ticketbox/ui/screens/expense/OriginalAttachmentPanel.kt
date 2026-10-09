package com.ticketbox.ui.screens.expense

import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.Role
import com.ticketbox.R
import com.ticketbox.data.repository.PendingOriginalCommand
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImagePresentation
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.viewmodel.OriginalAttachmentUiState
import com.ticketbox.viewmodel.OriginalAttachmentViewModel
import com.ticketbox.viewmodel.clearOriginalSelection
import com.ticketbox.viewmodel.continueCleanup
import com.ticketbox.viewmodel.recoverOriginal
import com.ticketbox.viewmodel.submitSelectedSource
import com.ticketbox.viewmodel.verifyReviewedImage

@Composable
fun OriginalAttachmentPanel(state: OriginalAttachmentUiState, viewModel: OriginalAttachmentViewModel,
    onSelectFile: () -> Unit, onResumeSelection: () -> Unit, initiallyExpanded: Boolean = false) {
    var expandedOverride by rememberSaveable(state.access?.binding) { mutableStateOf<Boolean?>(null) }
    val expanded = expandedOverride ?: (state.originalNeedsAttention() || initiallyExpanded)
    LaunchedEffect(expanded, state.access?.binding, state.health?.state) {
        if (expanded && state.canReadOriginal && state.image == null && !state.imageLoading) viewModel.loadImage()
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        SettingsEntryRow(
            title = stringResource(if (!expanded && state.canReadOriginal && state.health != null)
                R.string.original_view else R.string.original_title),
            subtitle = originalHealthLabel(state, compact = true),
            icon = R.drawable.ic_lucide_image,
            onClick = {
                expandedOverride = !expanded
            },
            options = SettingsEntryRowOptions(expanded = expanded),
        )
        AppStatusBanner(state.message, MessageTone.Neutral)
        if (expanded) {
            if (state.localIntent) OriginalLocalSelection(state, viewModel, onResumeSelection)
            OriginalReadAndRepair(state, viewModel, onSelectFile)
            OriginalHealthSection(state) { viewModel.refresh() }
            OriginalCleanupSection(state, viewModel)
            state.commands.forEach { OriginalCommandCard(it, state.busy, state.access?.canModify == true) { drop ->
                viewModel.recoverOriginal(it.row.id, drop)
            } }
        }
    }
}

private fun OriginalAttachmentUiState.originalNeedsAttention() = localIntent || commands.any { !it.delivered } ||
    health?.state in setOf("unverified", "missing", "corrupt", "unreadable")

@Composable
private fun originalHealthLabel(state: OriginalAttachmentUiState, compact: Boolean = false): String {
    if (compact && state.stale && state.health != null) return stringResource(R.string.original_stale)
    if (compact) return stringResource(when (state.health?.state) {
        "none" -> R.string.original_status_none
        "cleaned" -> R.string.original_status_cleaned
        "missing", "corrupt" -> R.string.original_status_replenish
        "unverified" -> R.string.original_status_unverified
        "verified" -> R.string.original_status_verified
        else -> R.string.original_status_unreadable
    })
    val labels = mapOf("none" to R.string.original_none, "cleaned" to R.string.original_cleaned,
        "missing" to R.string.original_missing, "corrupt" to R.string.original_corrupt,
        "unverified" to R.string.original_unverified, "verified" to R.string.original_verified,
        "unreadable" to R.string.original_unreadable)
    return stringResource(labels[state.health?.state] ?: R.string.original_health_failed)
}

@Composable
private fun OriginalHealthSection(state: OriginalAttachmentUiState, onRefresh: () -> Unit) {
    var expanded by rememberSaveable(state.access?.binding) { mutableStateOf(false) }
    SettingsEntryRow(
        title = stringResource(R.string.original_inspection_details),
        subtitle = state.health?.checkedAt?.let { stringResource(R.string.original_checked_at, displayTime(it)) }
            ?: stringResource(R.string.original_status_unreadable),
        icon = R.drawable.ic_lucide_info,
        onClick = { expanded = !expanded },
        options = SettingsEntryRowOptions(expanded = expanded),
    )
    if (expanded) {
        Text(originalHealthLabel(state), style = MaterialTheme.typography.bodyMedium)
        AppSecondaryButton(text = stringResource(R.string.original_check), enabled = !state.checking, onClick = onRefresh)
    }
}

@Composable
private fun OriginalReadAndRepair(state: OriginalAttachmentUiState, viewModel: OriginalAttachmentViewModel, onSelectFile: () -> Unit) {
    var verify by remember(state.access?.binding) { mutableStateOf(false) }
    if (state.image != null || state.imageLoading) {
        AppAsyncImage(state.image, presentation = AppAsyncImagePresentation(stringResource(
            if (state.imageLoading) R.string.expense_edit_large_image_loading else R.string.original_image_failed),
            stringResource(R.string.components_async_image_content_description), contentScale = ContentScale.Fit),
            layout = AppAsyncImageLayout(displayHeight = 420.dp), onDisplayed = viewModel::imageDisplayed)
        if (state.image != null && state.image.originalSha256 == null) Text(stringResource(R.string.original_verify_no_digest))
    }
    if (state.canReadOriginal) {
        AppSecondaryButton(text = stringResource(if (state.image == null) R.string.original_view else R.string.original_read_again),
            onClick = viewModel::loadImage, enabled = !state.imageLoading)
    }
    if (state.health?.state == "unverified") {
        AppPrimaryButton(text = stringResource(R.string.original_verify), modifier = Modifier.fillMaxWidth(),
            onClick = { verify = true }, enabled = state.canVerify)
    }
    if (verify) OriginalConfirmDialog(R.string.original_verify_explanation, {
        verify = false
        viewModel.verifyReviewedImage()
    }, { verify = false })
    if (state.selectionOperation != null) {
        val (action, explanation) = if (state.selectionOperation == "attach_original")
            R.string.original_attach to R.string.original_attach_context
        else R.string.original_replenish to R.string.original_replenish_context
        Text(stringResource(explanation), style = MaterialTheme.typography.bodyMedium)
        AppPrimaryButton(text = stringResource(action), modifier = Modifier.fillMaxWidth(),
            onClick = onSelectFile, enabled = state.canSubmit)
    }
}

@Composable
private fun OriginalCleanupSection(state: OriginalAttachmentUiState, viewModel: OriginalAttachmentViewModel) {
    var retry by remember(state.access?.binding) { mutableStateOf(false) }
    if (state.health?.cleanupError != null) Text(stringResource(R.string.original_cleanup_invalid))
    val cleanup = state.health?.cleanup ?: return
    OriginalCleanupOutcome(stringResource(R.string.original_file), cleanup.image, cleanup.imageError)
    OriginalCleanupOutcome(stringResource(R.string.original_thumbnail), cleanup.thumbnail, cleanup.thumbnailError)
    if (cleanup.image != "pending" && cleanup.thumbnail != "pending") return
    Text(stringResource(if (cleanup.policyEnabled) R.string.original_cleanup_pending else R.string.original_cleanup_paused))
    TextButton(onClick = { retry = true }, enabled = state.canSubmit && cleanup.policyEnabled) { Text(stringResource(R.string.original_cleanup_retry)) }
    TextButton(onClick = { viewModel.continueCleanup(true) }, enabled = state.canSubmit) {
        Text(stringResource(R.string.original_cleanup_cancel))
    }
    if (retry) OriginalConfirmDialog(R.string.original_cleanup_confirm, {
        retry = false
        viewModel.continueCleanup(false)
    }, { retry = false })
}

@Composable
private fun OriginalCleanupOutcome(label: String, outcome: String?, error: String?) {
    val stateLabel = when (outcome) {
        "pending" -> R.string.original_cleanup_part_pending
        "deleted" -> R.string.original_cleanup_part_deleted
        "cancelled" -> R.string.original_cleanup_part_cancelled
        else -> return
    }
    Text(stringResource(R.string.original_cleanup_part, label, stringResource(stateLabel)))
    if (error != null) Text(stringResource(if (error == "unlink_failed") R.string.original_cleanup_unlink_failed
        else R.string.original_cleanup_invalid))
}

@Composable
private fun OriginalLocalSelection(state: OriginalAttachmentUiState, viewModel: OriginalAttachmentViewModel, retry: () -> Unit) {
    val selection = state.selection
    if (selection != null && state.localIntentBound) {
        AppAsyncImage(selection.preview, presentation = AppAsyncImagePresentation(
            stringResource(R.string.original_selection_unavailable), stringResource(R.string.original_selected_image), contentScale = ContentScale.Fit),
            layout = AppAsyncImageLayout(displayHeight = 420.dp), onDisplayed = viewModel::selectedImageDisplayed)
        Text(selection.source.fileName, style = MaterialTheme.typography.bodySmall)
        val editable = state.selectionDisplayed && !state.busy && state.access?.canModify == true
        Row(Modifier.fillMaxWidth().minimumInteractiveComponentSize()
            .toggleable(state.selectionConfirmed, enabled = editable, role = Role.Checkbox, onValueChange = viewModel::confirmImageSelection),
            verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = state.selectionConfirmed, onCheckedChange = null, enabled = editable)
            Text(stringResource(R.string.original_selection_review), style = MaterialTheme.typography.bodyMedium)
        }
        AppPrimaryButton(text = stringResource(R.string.original_selection_submit), modifier = Modifier.fillMaxWidth(),
            onClick = viewModel::submitSelectedSource, enabled = state.canConfirmSelection)
    } else {
        Text(stringResource(if (state.localIntentBound) R.string.original_source_saved else R.string.original_source_other_binding))
        TextButton(onClick = retry, enabled = !state.busy && state.localIntentBound && state.access?.canModify == true) { Text(stringResource(R.string.original_source_retry)) }
    }
    TextButton(onClick = viewModel::clearOriginalSelection, enabled = !state.busy) { Text(stringResource(R.string.original_source_cancel)) }
}

@Composable
private fun OriginalCommandCard(command: PendingOriginalCommand, busy: Boolean, canModify: Boolean, recover: (Boolean) -> Unit) {
    var stop by remember(command.row.id) { mutableStateOf(false) }
    val operationLabels = mapOf("attach_original" to R.string.original_attach, "verify_original" to R.string.original_verify, "replenish_original" to R.string.original_replenish,
        "retry_original_cleanup" to R.string.original_cleanup_retry, "cancel_original_cleanup" to R.string.original_cleanup_cancel)
    val label = stringResource(operationLabels[command.payload?.operation] ?: R.string.original_title)
    if (command.delivered) {
        Text(stringResource(R.string.original_receipt, label, requireNotNull(command.receipt).acceptedAt))
    } else {
        Text(label)
        Text(stringResource(if (command.canDiscard) originalFailureLabel(command.row.lastError) else R.string.original_pending))
        command.payload?.file?.metadata?.fileName?.let { Text(it) }
        if (command.canRetry) TextButton(onClick = { recover(false) }, enabled = !busy && canModify) {
            Text(stringResource(R.string.original_retry))
        }
        if (command.canDiscard) TextButton(onClick = { stop = true }, enabled = !busy) { Text(stringResource(R.string.original_stop)) }
    }
    if (stop) OriginalConfirmDialog(R.string.original_stop_confirm, { stop = false; recover(true) }, { stop = false })
}

private fun originalFailureLabel(code: String?): Int = when (code) {
    "image_replenishment_mismatch" -> R.string.error_image_replenishment_mismatch
    "state_conflict" -> R.string.original_review_conflict
    "original_review_conflict" -> R.string.error_original_review_conflict
    "attachment_cleanup_changed" -> R.string.error_attachment_cleanup_changed
    "original_already_verified" -> R.string.error_original_already_verified
    "original_already_associated" -> R.string.error_original_already_associated
    "original_identity_unverified" -> R.string.error_original_identity_unverified
    "attachment_cleanup_invalid" -> R.string.error_attachment_cleanup_invalid
    else -> R.string.original_attention
}

@Composable
private fun OriginalConfirmDialog(message: Int, confirm: () -> Unit, dismiss: () -> Unit) {
    AlertDialog(onDismissRequest = dismiss, text = { Text(stringResource(message)) },
        confirmButton = { TextButton(onClick = confirm) { Text(stringResource(R.string.original_continue)) } },
        dismissButton = { TextButton(onClick = dismiss) { Text(stringResource(R.string.original_cancel)) } })
}
