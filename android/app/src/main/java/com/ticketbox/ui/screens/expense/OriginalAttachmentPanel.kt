package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.data.repository.PendingOriginalCommand
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAsyncImage
import com.ticketbox.ui.components.AppAsyncImageLayout
import com.ticketbox.ui.components.AppAsyncImagePresentation
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.OriginalAttachmentUiState
import com.ticketbox.viewmodel.OriginalAttachmentViewModel
import com.ticketbox.viewmodel.clearOriginalSelection
import com.ticketbox.viewmodel.continueCleanup
import com.ticketbox.viewmodel.recoverOriginal
import com.ticketbox.viewmodel.verifyReviewedImage

@Composable
fun OriginalAttachmentPanel(state: OriginalAttachmentUiState, viewModel: OriginalAttachmentViewModel,
    onSelectFile: () -> Unit, onResumeSelection: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.original_title))
        AppStatusBanner(state.message, MessageTone.Neutral)
        OriginalHealthSection(state) { viewModel.refresh() }
        if (state.localIntent) OriginalLocalSelection(state, onResumeSelection, viewModel::clearOriginalSelection)
        OriginalReadAndRepair(state, viewModel, onSelectFile)
        OriginalCleanupSection(state, viewModel)
        state.commands.forEach { OriginalCommandCard(it, state.busy, state.access?.canModify == true) { drop ->
            viewModel.recoverOriginal(it.row.id, drop)
        } }
    }
}

@Composable
private fun OriginalHealthSection(state: OriginalAttachmentUiState, onRefresh: () -> Unit) {
    val labels = mapOf("none" to R.string.original_none, "cleaned" to R.string.original_cleaned,
        "missing" to R.string.original_missing, "corrupt" to R.string.original_corrupt,
        "unverified" to R.string.original_unverified, "verified" to R.string.original_verified,
        "unreadable" to R.string.original_unreadable)
    Text(stringResource(labels[state.health?.state] ?: R.string.original_health_failed))
    if (state.stale && state.health != null) Text(stringResource(R.string.original_stale))
    state.health?.checkedAt?.let { Text(stringResource(R.string.original_checked_at, it)) }
    TextButton(onClick = onRefresh, enabled = !state.checking) { Text(stringResource(R.string.original_check)) }
}

@Composable
private fun OriginalReadAndRepair(state: OriginalAttachmentUiState, viewModel: OriginalAttachmentViewModel, onSelectFile: () -> Unit) {
    var verify by remember(state.access?.binding) { mutableStateOf(false) }
    if (state.canReadOriginal) {
        TextButton(onClick = viewModel::loadImage, enabled = !state.imageLoading) { Text(stringResource(R.string.original_view)) }
    }
    state.image?.let { image ->
        AppAsyncImage(image, presentation = AppAsyncImagePresentation(stringResource(R.string.original_image_failed),
            stringResource(R.string.components_async_image_content_description), contentScale = ContentScale.Fit),
            layout = AppAsyncImageLayout(displayHeight = 420.dp), onDisplayed = viewModel::imageDisplayed)
        if (image.originalSha256 == null) Text(stringResource(R.string.original_verify_no_digest))
    }
    if (state.health?.state == "unverified") {
        TextButton(onClick = { verify = true }, enabled = state.canVerify) { Text(stringResource(R.string.original_verify)) }
    }
    if (verify) OriginalConfirmDialog(R.string.original_verify_explanation, {
        verify = false
        viewModel.verifyReviewedImage()
    }, { verify = false })
    if (state.health?.expectedSha256 != null && state.health.state in setOf("missing", "corrupt", "cleaned", "unreadable")) {
        TextButton(onClick = onSelectFile, enabled = state.canSubmit) { Text(stringResource(R.string.original_replenish)) }
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
private fun OriginalLocalSelection(state: OriginalAttachmentUiState, retry: () -> Unit, cancel: () -> Unit) {
    Text(stringResource(if (state.localIntentBound) R.string.original_source_saved else R.string.original_source_other_binding))
    TextButton(onClick = retry, enabled = !state.busy && state.localIntentBound && state.access?.canModify == true) { Text(stringResource(R.string.original_source_retry)) }
    TextButton(onClick = cancel, enabled = !state.busy) { Text(stringResource(R.string.original_source_cancel)) }
}

@Composable
private fun OriginalCommandCard(command: PendingOriginalCommand, busy: Boolean, canModify: Boolean, recover: (Boolean) -> Unit) {
    var stop by remember(command.row.id) { mutableStateOf(false) }
    val operationLabels = mapOf("verify_original" to R.string.original_verify, "replenish_original" to R.string.original_replenish,
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
    "image_replenishment_mismatch" -> R.string.original_digest_mismatch
    "state_conflict", "original_review_conflict", "attachment_cleanup_changed", "original_already_verified" -> R.string.original_review_conflict
    "original_identity_unverified" -> R.string.original_unverified
    "attachment_cleanup_invalid" -> R.string.original_cleanup_invalid
    else -> R.string.original_attention
}

@Composable
private fun OriginalConfirmDialog(message: Int, confirm: () -> Unit, dismiss: () -> Unit) {
    AlertDialog(onDismissRequest = dismiss, text = { Text(stringResource(message)) },
        confirmButton = { TextButton(onClick = confirm) { Text(stringResource(R.string.original_continue)) } },
        dismissButton = { TextButton(onClick = dismiss) { Text(stringResource(R.string.original_cancel)) } })
}
