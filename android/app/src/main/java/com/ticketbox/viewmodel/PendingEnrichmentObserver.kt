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
 * Observes only the durable enrichment tasks returned by uploads initiated in
 * this running Pending consumer. The server task row remains the fact owner;
 * this class owns no persisted queue and resumes nothing after process death.
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
    private var latestFeedback: PendingEnrichmentFeedback? = null

    fun track(receipt: PendingUploadReceipt) {
        if (!canObserve()) return
        active.remove(receipt.enrichmentTaskPublicId)?.job?.cancel()
        paused.remove(receipt.enrichmentTaskPublicId)
        latestFeedback = null

        val job = scope.launch(start = CoroutineStart.LAZY) {
            observe(receipt)
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
        receipts.forEach(::track)
    }

    fun clear() {
        val jobs = active.values.map(TrackedTask::job)
        active.clear()
        paused.clear()
        latestFeedback = null
        jobs.forEach(Job::cancel)
        emitState()
    }

    private suspend fun observe(receipt: PendingUploadReceipt) {
        while (canObserve()) {
            val task = fetchTask(receipt.enrichmentTaskPublicId).getOrElse {
                pause(receipt)
                return
            }
            if (task.status in POLLING_STATUSES) {
                delay(pollIntervalMs)
                continue
            }
            finish(receipt, task.toPendingEnrichmentFeedbackKind())
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
