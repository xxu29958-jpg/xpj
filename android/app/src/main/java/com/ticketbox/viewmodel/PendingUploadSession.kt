package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.ScreenshotUploadRequest
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private data class PendingUploadItem(
    val imageRef: String,
    val prepare: suspend (String) -> PreparedUploadImage?,
)

private class PendingUploadBatch(
    val items: MutableList<PendingUploadItem>,
    val binding: LogicalSessionBinding,
    val generation: Int,
) {
    var cursor = 0
    var failedCount = 0
    var lastFailure: UiText? = null
    var preparedImage: PreparedUploadImage? = null
}

/** One VM-lifetime upload intent. Capacity rejection retains this cursor and these bytes. */
internal class PendingUploadSession(
    private val scope: CoroutineScope,
    private val repository: PendingReviewActions,
    private val currentGeneration: () -> Int,
    private val canWrite: () -> Boolean,
    private val onState: (uploading: Boolean, retryable: Boolean, message: UiText?) -> Unit,
    private val onReceipt: (PendingUploadReceipt) -> Unit,
) {
    private var batch: PendingUploadBatch? = null
    private var job: Job? = null
    private var running = false

    /** Acceptance is synchronous, before the Route may consume its launch action. */
    fun accept(imageRefs: List<String>, prepare: suspend (String) -> PreparedUploadImage?): Boolean {
        if (!canWrite() || !scope.isActive || imageRefs.isEmpty()) return false
        val items = imageRefs.map { PendingUploadItem(it, prepare) }
        batch?.let { retained ->
            if (!isCurrent(retained)) return false
            retained.items.addAll(items)
            // A new share joins the tail; it does not retry the paused image.
            return true
        }
        val binding = repository.currentUploadBinding() ?: return false
        val accepted = PendingUploadBatch(
            items.toMutableList(), binding, currentGeneration(),
        )
        batch = accepted
        launch(accepted)
        return true
    }

    fun retry() {
        val retained = batch ?: return
        if (running || retained.preparedImage == null || !isCurrent(retained)) return
        launch(retained)
    }

    /** Invalidate only this owner; a stale coroutine cannot release a newer batch. */
    fun invalidate(message: UiText? = null): Boolean {
        val hadIntent = batch != null
        batch = null
        running = false
        job?.cancel()
        job = null
        if (hadIntent) onState(false, false, message)
        return hadIntent
    }

    private fun launch(accepted: PendingUploadBatch) {
        running = true
        onState(true, false, null)
        job = scope.launch(start = CoroutineStart.LAZY) { drain(accepted) }
        job?.start()
    }

    private suspend fun drain(accepted: PendingUploadBatch) {
        try {
            while (isCurrent(accepted) && accepted.cursor < accepted.items.size) {
                val image = accepted.preparedImage ?: prepare(accepted)
                if (!isCurrent(accepted)) return
                if (image == null) {
                    accepted.cursor += 1
                    continue
                }
                accepted.preparedImage = image
                val result = repository.uploadScreenshot(ScreenshotUploadRequest(
                    fileName = image.fileName, contentType = image.contentType, bytes = image.bytes,
                    preparationDurationMs = image.preparationDurationMs, sourceSizeBytes = image.sourceSizeBytes,
                    expectedBinding = accepted.binding,
                ))
                if (!isCurrent(accepted)) return
                val error = result.exceptionOrNull()
                if (error is CancellationException) throw error
                if ((error as? RepositoryException)?.errorCode == "enrichment_capacity_full") {
                    running = false
                    onState(false, true, UiText.res(R.string.pending_msg_upload_capacity_full))
                    return
                }
                if (result.isSuccess) {
                    onReceipt(result.getOrThrow())
                } else {
                    accepted.failedCount += 1
                    accepted.lastFailure = error?.toUiText(R.string.pending_msg_upload_failed)
                }
                accepted.preparedImage = null
                accepted.cursor += 1
            }
            if (isCurrent(accepted)) finish(accepted)
        } catch (error: CancellationException) {
            if (batch === accepted) invalidate()
            throw error
        } finally {
            if (batch === accepted) running = false
        }
    }

    private suspend fun prepare(accepted: PendingUploadBatch): PreparedUploadImage? {
        val image = try {
            val item = accepted.items[accepted.cursor]
            item.prepare(item.imageRef)
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            null
        }
        if (image == null) {
            accepted.failedCount += 1
            accepted.lastFailure = UiText.res(R.string.pending_msg_upload_unreadable)
        }
        return image
    }

    private fun isCurrent(accepted: PendingUploadBatch): Boolean {
        if (batch !== accepted) return false
        if (accepted.generation != currentGeneration() ||
            accepted.binding != repository.currentUploadBinding()
        ) {
            invalidate(UiText.res(R.string.pending_msg_upload_ledger_switched))
            return false
        }
        return canWrite() && batch === accepted
    }

    private fun finish(accepted: PendingUploadBatch) {
        batch = null
        job = null
        running = false
        val message = if (accepted.failedCount > 0 && accepted.items.size > 1) {
            UiText.res(R.string.pending_msg_share_partial_failure, accepted.failedCount)
        } else {
            accepted.lastFailure
        }
        onState(false, false, message)
    }
}
