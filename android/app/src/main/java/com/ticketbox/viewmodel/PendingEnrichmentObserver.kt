package com.ticketbox.viewmodel

import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.domain.model.PendingUploadReceipt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

data class PendingEnrichmentUiState(
    val activeCount: Int = 0,
    val feedback: PendingEnrichmentFeedback? = null,
)

data class PendingEnrichmentFeedback(
    val expenseId: Long,
    val kind: PendingEnrichmentFeedbackKind,
)

enum class PendingEnrichmentFeedbackKind {
    Updated,
    NoResult,
    Conflict,
    Failed,
    Cancelled,
    NotPending,
    Unavailable,
}

/**
 * Observes server-owned tasks from durable upload receipts. A reopened consumer
 * probes only receipts still present in its authoritative Pending list. Successful
 * history stays quiet; unfinished outcomes stay visible and active tasks resume polling.
 */
internal class PendingEnrichmentObserver(
    private val scope: CoroutineScope,
    private val fetchTask: suspend (String) -> Result<PendingEnrichmentTask>,
    private val canObserve: () -> Boolean,
    private val onStateChanged: (PendingEnrichmentUiState) -> Unit,
    private val onTerminal: () -> Unit,
    private val pollIntervalMs: Long = DEFAULT_POLL_INTERVAL_MS,
) {
    private val active = linkedMapOf<String, TrackedTask>()
    private val paused = linkedMapOf<String, PendingUploadReceipt>()
    private val observed = mutableSetOf<String>()
    private var latestFeedback: PendingEnrichmentFeedback? = null

    fun track(receipt: PendingUploadReceipt) {
        start(receipt, restoring = false)
    }

    fun restore(receipts: List<PendingUploadReceipt>) {
        receipts.forEach { start(it, restoring = true) }
    }

    private fun start(receipt: PendingUploadReceipt, restoring: Boolean) {
        if (!canObserve() || !observed.add(receipt.enrichmentTaskPublicId)) return
        latestFeedback = null

        val job = scope.launch(start = CoroutineStart.LAZY) {
            observe(receipt, restoring)
        }
        active[receipt.enrichmentTaskPublicId] = TrackedTask(receipt, job)
        emitState()
        job.start()
    }

    fun retryPaused() {
        if (!canObserve()) {
            clear()
            return
        }
        val receipts = paused.values.toList()
        paused.clear()
        receipts.forEach {
            observed.remove(it.enrichmentTaskPublicId)
            track(it)
        }
    }

    fun clear() {
        val jobs = active.values.map(TrackedTask::job)
        active.clear()
        paused.clear()
        observed.clear()
        latestFeedback = null
        jobs.forEach(Job::cancel)
        emitState()
    }

    private suspend fun observe(receipt: PendingUploadReceipt, restoring: Boolean) {
        var notifyTerminal = !restoring
        while (canObserve()) {
            val result = fetchTask(receipt.enrichmentTaskPublicId)
            if (!canObserve()) break
            val task = result.getOrElse {
                pause(receipt)
                return
            }
            if (task.status in POLLING_STATUSES) {
                notifyTerminal = true
                delay(pollIntervalMs)
                continue
            }
            val kind = task.toPendingEnrichmentFeedbackKind()
            if (notifyTerminal || kind != PendingEnrichmentFeedbackKind.Updated && kind != PendingEnrichmentFeedbackKind.NoResult) {
                finish(receipt, kind)
            } else {
                discard(receipt.enrichmentTaskPublicId)
                // The Pending GET may have preceded this task's commit. Read once after that
                // known update, without replaying historical success feedback or the upload.
                if (task.status == "completed" && task.outcome == PendingEnrichmentOutcome.Updated) onTerminal()
            }
            return
        }
        discard(receipt.enrichmentTaskPublicId)
    }

    private fun pause(receipt: PendingUploadReceipt) {
        active.remove(receipt.enrichmentTaskPublicId)
        paused[receipt.enrichmentTaskPublicId] = receipt
        latestFeedback = receipt.feedback(PendingEnrichmentFeedbackKind.Unavailable)
        emitState()
    }

    private fun finish(receipt: PendingUploadReceipt, kind: PendingEnrichmentFeedbackKind) {
        active.remove(receipt.enrichmentTaskPublicId)
        paused.remove(receipt.enrichmentTaskPublicId)
        latestFeedback = receipt.feedback(kind)
        emitState()
        onTerminal()
    }

    private fun discard(publicId: String) {
        active.remove(publicId)
        paused.remove(publicId)
        emitState()
    }

    private fun emitState() {
        onStateChanged(
            PendingEnrichmentUiState(
                activeCount = active.size,
                feedback = latestFeedback,
            ),
        )
    }

    private data class TrackedTask(
        val receipt: PendingUploadReceipt,
        val job: Job,
    )

    private companion object {
        const val DEFAULT_POLL_INTERVAL_MS = 1_000L
        val POLLING_STATUSES = setOf("queued", "running")
    }
}

private fun PendingUploadReceipt.feedback(kind: PendingEnrichmentFeedbackKind) = PendingEnrichmentFeedback(
    expenseId = expenseId,
    kind = kind,
)

internal fun PendingEnrichmentTask.toPendingEnrichmentFeedbackKind(): PendingEnrichmentFeedbackKind = when (status) {
    "completed" -> when (outcome) {
        PendingEnrichmentOutcome.Updated -> PendingEnrichmentFeedbackKind.Updated
        PendingEnrichmentOutcome.NoResult -> PendingEnrichmentFeedbackKind.NoResult
        PendingEnrichmentOutcome.Conflict -> PendingEnrichmentFeedbackKind.Conflict
        PendingEnrichmentOutcome.NotPending -> PendingEnrichmentFeedbackKind.NotPending
        null -> PendingEnrichmentFeedbackKind.Failed
    }
    "cancelled" -> PendingEnrichmentFeedbackKind.Cancelled
    else -> PendingEnrichmentFeedbackKind.Failed
}
