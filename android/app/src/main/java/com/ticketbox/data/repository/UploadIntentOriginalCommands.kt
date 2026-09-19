package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.OriginalHealthDto
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

private val originalErrors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Original")

@OptIn(ExperimentalCoroutinesApi::class)
internal fun UploadIntentRepository.observeOriginalAttachmentCommands() = apiProvider.observeActiveLedgerAccess().flatMapLatest { access ->
    if (access == null) flowOf(OriginalCommandObservation(null, emptyList()))
    else outbox.observeActiveByTypes(setOf(PendingMutationType.OriginalAttachment), includeCompleted = true).map { rows ->
        if (guard.captureLogicalBinding() != access.binding) OriginalCommandObservation(null, emptyList())
        else OriginalCommandObservation(access, rows.map { row -> PendingOriginalCommand(row, readOriginalPayload(row),
            row.receiptJson?.let { runCatching { originalReceiptAdapter.fromJson(it) }.getOrNull() }) })
    }
}

internal suspend fun UploadIntentRepository.readOriginalHealth(id: Long): Result<OriginalHealthDto> =
    originalErrors.safeCall { guard.bind().call { it.originalHealth(id) } }

internal suspend fun UploadIntentRepository.acceptOriginalAttachment(request: OriginalSubmission): Result<Long> = originalErrors.safeCall {
    require(isUploadIntentFileKey(request.key))
    val bound = guard.bindExact(request.payload.origin)
    requireOriginalWriter()
    files.acceptBatch(
        sources = if (request.payload.operation == "replenish_original") listOf(
            UploadIntentFileSource(request.key, request.payload.file) { request.prepareOriginalSource() },
        ) else emptyList(),
        beforePrepare = {
            outbox.originalUploadRows(bound, listOf(request.key), PendingMutationType.OriginalAttachment).singleOrNull()?.let { row ->
                val original = requireNotNull(readOriginalPayload(row))
                check(original.copy(file = null) == request.payload.copy(file = null))
                outbox.schedulePending()
                row.id
            }
        },
        persist = { descriptors ->
            requireOriginalWriter()
            val payload = request.payload.copy(file = descriptors.singleOrNull())
            require(payload.supported())
            val intent = PendingMutationIntent(PendingMutationType.OriginalAttachment, "expense:${payload.expenseId}",
                originalPayloadAdapter.toJson(payload), payload.expectedRowVersion, request.key)
            outbox.enqueueUploadBatch(bound, listOf(intent)).single()
        },
    )
}

internal suspend fun UploadIntentRepository.recoverOriginalAttachment(binding: LogicalSessionBinding, rowId: Long,
    drop: Boolean): Result<Unit> = originalErrors.safeCall {
    val bound = guard.bindExact(binding)
    val observation = observeOriginalCommands().first()
    check(observation.access?.binding == binding)
    val pending = requireNotNull(observation.commands.singleOrNull { it.row.id == rowId })
    val changed = if (drop && pending.canDiscard) {
        if (pending.row.status == PendingMutationStatus.Conflict) outbox.resolveConflict(rowId, ConflictResolution.DropMine, bound)
        else outbox.resolveFailed(rowId, FailedResolution.Drop, bound)
    } else {
        requireOriginalWriter()
        check(pending.canRetry)
        outbox.resolveFailed(rowId, FailedResolution.Retry(), bound)
    }
    check(changed)
}

private fun UploadIntentRepository.requireOriginalWriter() {
    if (!ledgerRoleCanModify(apiProvider.currentLedgerRole())) throw RepositoryException(
        "Original attachment requires write access", localFailure = LocalRepositoryFailure.OriginalWriterRequired,
    )
}

private suspend fun OriginalSubmission.prepareOriginalSource() = try {
    prepare?.invoke()
} catch (error: kotlinx.coroutines.CancellationException) {
    throw error
} catch (_: Exception) {
    throw RepositoryException("Selected original is unavailable", localFailure = LocalRepositoryFailure.OriginalSourceUnavailable)
}
