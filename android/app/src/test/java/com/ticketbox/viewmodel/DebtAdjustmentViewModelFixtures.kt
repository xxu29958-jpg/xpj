package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtWriteActions
import com.ticketbox.data.repository.DebtWriteObservation
import com.ticketbox.data.repository.DebtAdjustmentPayload
import com.ticketbox.data.repository.DebtWriteSubject
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtWrite
import com.ticketbox.domain.model.Debt
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.combine

internal data class AdjustmentSaveCall(
    val binding: LogicalSessionBinding,
    val debt: Debt,
    val amountCents: Long,
    val reason: String,
)

internal data class RepaymentSaveCall(
    val binding: LogicalSessionBinding,
    val debt: Debt,
    val amountCents: Long,
)

internal data class AdjustmentRecoveryCall(
    val binding: LogicalSessionBinding,
    val pending: PendingDebtWrite,
    val drop: Boolean,
)

internal class FakeDebtWriteActions(
    val access: MutableStateFlow<LedgerAccessContext?> =
        MutableStateFlow(LedgerAccessContext(adjustmentBinding(), canModify = true)),
) : DebtWriteActions {
    val rows = MutableStateFlow<List<PendingDebtWrite>>(emptyList())
    val saveCalls = mutableListOf<AdjustmentSaveCall>()
    val repaymentCalls = mutableListOf<RepaymentSaveCall>()
    val recoveryCalls = mutableListOf<AdjustmentRecoveryCall>()
    var saveResult = Result.success(1L)
    var saveGate: CompletableDeferred<Unit>? = null

    override fun currentAccess() = access.value
    override fun observeActiveLedgerAccess() = access
    override fun observeWrites() = flow {
        var previous = access.value?.binding
        var initial = true
        val seen = mutableSetOf<Long>()
        combine(access, rows) { current, pending -> current?.binding to pending }.collect { (binding, pending) ->
            if (binding != previous) { previous = binding; initial = true; seen.clear() }
            val bound = pending.filter { it.row.ownerKey == binding?.ownerKey && it.row.ledgerId == binding?.ledgerId &&
                it.row.serverUrl == binding?.serverUrl }
            val terminal = bound.filter { it.isTerminal }
            val arrived = if (initial) emptyList() else terminal.filter { it.row.id !in seen }
            seen += terminal.map { it.row.id }
            emit(DebtWriteObservation(binding, bound, initial, arrived))
            initial = false
        }
    }
    override fun observeWrites(binding: LogicalSessionBinding, publicId: String) = rows.map { pending ->
        pending.filter { it.row.serverUrl == binding.serverUrl && it.row.ledgerId == binding.ledgerId &&
            it.row.ownerKey == binding.ownerKey && it.row.targetId == "debt:$publicId" }
    }
    override fun describeWrite(row: OutboxRow) = rows.value.singleOrNull { it.row == row }

    override suspend fun save(binding: LogicalSessionBinding, debt: Debt, amountCents: Long, reason: String): Result<Long> {
        saveCalls += AdjustmentSaveCall(binding, debt, amountCents, reason)
        val captured = saveResult
        saveGate?.await()
        return captured
    }

    override suspend fun saveRepayment(binding: LogicalSessionBinding, debt: Debt, amountCents: Long): Result<Long> {
        repaymentCalls += RepaymentSaveCall(binding, debt, amountCents)
        val captured = saveResult
        saveGate?.await()
        return captured
    }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtWrite, drop: Boolean): Result<Unit> {
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
): PendingDebtWrite {
    val payload = DebtAdjustmentPayload(
        revision = 1,
        subject = DebtWriteSubject("debt-1", "房东", "CNY"),
        originSessionGeneration = binding.sessionGeneration,
        originBindingRevision = binding.bindingRevision,
        request = DebtAdjustmentCreateRequestDto(amountCents = -5_000, reason = "减免", expectedRowVersion = 7),
    )
    return PendingDebtWrite(
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

internal class AdjustmentDetailActions : DebtActions by FakeDebtActions() {
    val mutations = mutableListOf<String>()
    override suspend fun voidDebt(publicId: String, expectedRowVersion: Long, reason: String): Result<Debt> {
        mutations += "void:$publicId:$expectedRowVersion:$reason"
        return getResult
    }
    override suspend fun voidRepayment(publicId: String, repaymentPublicId: String,
        expectedRowVersion: Long, reason: String): Result<Debt> {
        mutations += "repaymentVoid:$publicId:$repaymentPublicId:$expectedRowVersion:$reason"
        return getResult
    }
    override suspend fun setDebtKind(publicId: String, expectedRowVersion: Long, debtKind: String): Result<Debt> {
        mutations += "kind:$publicId:$expectedRowVersion:$debtKind"
        return getResult
    }
    var getResult: Result<Debt> = Result.success(sampleDebt().copy(rowVersion = 7))
    var getGate: CompletableDeferred<Unit>? = null
    val getCalls = mutableListOf<String>()

    override suspend fun getDebt(publicId: String): Result<Debt> {
        getCalls += publicId
        val captured = getResult
        getGate?.await()
        return captured
    }
}
