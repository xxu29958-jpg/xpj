package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.repository.DebtAdjustmentActions
import com.ticketbox.data.repository.DebtAdjustmentPayload
import com.ticketbox.data.repository.DebtAdjustmentSubject
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtAdjustment
import com.ticketbox.domain.model.Debt
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map

internal data class AdjustmentSaveCall(
    val binding: LogicalSessionBinding,
    val debt: Debt,
    val amountCents: Long,
    val reason: String,
)

internal data class AdjustmentRecoveryCall(
    val binding: LogicalSessionBinding,
    val pending: PendingDebtAdjustment,
    val drop: Boolean,
)

internal class FakeDebtAdjustmentActions : DebtAdjustmentActions {
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(adjustmentBinding(), canModify = true))
    val rows = MutableStateFlow<List<PendingDebtAdjustment>>(emptyList())
    val saveCalls = mutableListOf<AdjustmentSaveCall>()
    val recoveryCalls = mutableListOf<AdjustmentRecoveryCall>()
    var saveResult = Result.success(1L)
    var saveGate: CompletableDeferred<Unit>? = null

    override fun currentAccess() = access.value
    override fun observeActiveLedgerAccess() = access
    override fun observeAdjustments(binding: LogicalSessionBinding, publicId: String) = rows.map { pending ->
        pending.filter { it.row.serverUrl == binding.serverUrl && it.row.ledgerId == binding.ledgerId &&
            it.row.ownerKey == binding.ownerKey && it.row.targetId == "debt:$publicId" }
    }
    override fun describeAdjustment(row: OutboxRow) = rows.value.singleOrNull { it.row == row }

    override suspend fun save(binding: LogicalSessionBinding, debt: Debt, amountCents: Long, reason: String): Result<Long> {
        saveCalls += AdjustmentSaveCall(binding, debt, amountCents, reason)
        val captured = saveResult
        saveGate?.await()
        return captured
    }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtAdjustment, drop: Boolean): Result<Unit> {
        recoveryCalls += AdjustmentRecoveryCall(binding, pending, drop)
        return Result.success(Unit)
    }
}

internal fun adjustmentBinding() = LogicalSessionBinding(
    serverUrl = "https://example.test",
    ledgerId = "owner",
    ownerKey = "test-owner",
    sessionGeneration = "session-1",
    bindingRevision = "binding-1",
)

internal fun pendingAdjustment(
    id: Long = 1L,
    status: PendingMutationStatus = PendingMutationStatus.Pending,
    binding: LogicalSessionBinding = adjustmentBinding(),
): PendingDebtAdjustment {
    val payload = DebtAdjustmentPayload(
        revision = 1,
        subject = DebtAdjustmentSubject("debt-1", "房东", "CNY"),
        originSessionGeneration = binding.sessionGeneration,
        originBindingRevision = binding.bindingRevision,
        request = DebtAdjustmentCreateRequestDto(amountCents = -5_000, reason = "减免", expectedRowVersion = 7),
    )
    return PendingDebtAdjustment(
        row = OutboxRow(
            id = id, serverUrl = binding.serverUrl, ledgerId = binding.ledgerId, ownerKey = binding.ownerKey,
            type = PendingMutationType.RecordDebtAdjustment, targetId = "debt:debt-1",
            payloadJson = com.ticketbox.OutboxAdapterGraph().debtAdjustmentAdapter.toJson(payload),
            expectedRowVersion = 7, status = status, retryCount = 0,
            lastError = if (status == PendingMutationStatus.Failed) "network unavailable" else null,
            createdAt = "2026-09-06T08:00:00Z", attemptedAt = null,
            completedAt = if (status == PendingMutationStatus.Done) "2026-09-06T08:01:00Z" else null,
            idempotencyKey = "original-adjustment-$id",
        ),
        intent = payload,
    )
}
