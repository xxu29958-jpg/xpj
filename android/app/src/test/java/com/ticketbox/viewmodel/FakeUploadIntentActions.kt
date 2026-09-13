package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingUploadIntent
import com.ticketbox.data.repository.UploadAcceptance
import com.ticketbox.data.repository.UploadBatchPosition
import com.ticketbox.data.repository.UploadBatchRequest
import com.ticketbox.data.repository.UploadIntentActions
import com.ticketbox.data.repository.UploadIntentFileDescriptor
import com.ticketbox.data.repository.UploadIntentFileMetadata
import com.ticketbox.data.repository.UploadIntentObservation
import com.ticketbox.data.repository.UploadScreenshotPayload
import com.ticketbox.data.repository.uploadItemKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.onStart

/** Typed observation/action seam only. No file persistence, HTTP sender or drain loop lives here. */
internal class FakeUploadIntentActions(
    initialAccess: LedgerAccessContext = LedgerAccessContext(uploadTestBinding(), true),
    private val ledgerChanges: Flow<String?> = emptyFlow(),
) : UploadIntentActions {
    val snapshots = MutableStateFlow(UploadIntentObservation(initialAccess, emptyList()))
    var currentBinding = initialAccess.binding
    val accepted = mutableListOf<UploadBatchRequest>()
    val recoveries = mutableListOf<Triple<LogicalSessionBinding, String, Boolean>>()
    var accept: suspend (UploadBatchRequest) -> Result<UploadAcceptance> = {
        Result.success(UploadAcceptance(it.id, listOf(1L)))
    }
    var recover: suspend () -> Result<Unit> = { Result.success(Unit) }

    override fun currentUploadBinding(): LogicalSessionBinding = currentBinding

    override fun observeUploadIntents(): Flow<UploadIntentObservation> = combine(
        snapshots, ledgerChanges.onStart { emit(currentBinding.ledgerId) },
    ) { snapshot, ledger ->
        val access = snapshot.access?.let {
            it.copy(binding = it.binding.copy(ledgerId = ledger ?: it.binding.ledgerId))
        }
        access?.binding?.let { currentBinding = it }
        snapshot.copy(access = access, uploads = snapshot.uploads.filter { it.row.ledgerId == access?.binding?.ledgerId })
    }

    override suspend fun acceptUploadBatch(request: UploadBatchRequest): Result<UploadAcceptance> {
        accepted += request
        return accept(request)
    }

    override suspend fun recoverUploadGroup(
        expectedBinding: LogicalSessionBinding,
        groupId: String,
        drop: Boolean,
    ): Result<Unit> {
        recoveries += Triple(expectedBinding, groupId, drop)
        return recover()
    }

    fun publish(vararg rows: PendingUploadIntent) {
        snapshots.value = snapshots.value.copy(uploads = rows.toList())
    }
}

internal const val UPLOAD_TEST_BATCH = "00000000-0000-0000-0000-000000000001"

internal fun uploadTestBinding() = LogicalSessionBinding(
    "https://test.local", "test-ledger", "test-owner", "test-generation", "test-revision",
)

internal fun observedUpload(
    id: Long,
    status: PendingMutationStatus = PendingMutationStatus.Pending,
    lastError: String? = null,
    binding: LogicalSessionBinding = uploadTestBinding(),
): PendingUploadIntent {
    val index = (id - 1).toInt()
    val key = uploadItemKey(UPLOAD_TEST_BATCH, index)
    val payload = UploadScreenshotPayload(
        1, UploadBatchPosition(UPLOAD_TEST_BATCH, index, 10, UPLOAD_TEST_BATCH), binding, "Asia/Shanghai",
        UploadIntentFileDescriptor(key, 3L, "0".repeat(64), UploadIntentFileMetadata("$id.jpg", "image/jpeg", 0, 3)),
    )
    val receipt = if (status == PendingMutationStatus.Done) UploadResponseDto(
        id, "expense-$id", "task-$id", "pending", "uploaded", "hash-$id", null, "none", null,
    ) else null
    return PendingUploadIntent(
        OutboxRow(
            id, binding.serverUrl, binding.ledgerId, binding.ownerKey, PendingMutationType.UploadScreenshot,
            "upload_batch:$UPLOAD_TEST_BATCH", "original-$id", 0, status, 0, lastError,
            "2026-09-07T00:00:00Z", null, if (receipt != null) "2026-09-07T00:01:00Z" else null,
            key, blocksFollowing = lastError == "enrichment_capacity_full",
        ),
        payload, receipt,
    )
}
