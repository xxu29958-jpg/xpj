package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.IncomePlanSubmissionPayload
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf

internal data class IncomePlanCreateCall(
    val binding: LogicalSessionBinding,
    val draft: IncomePlanDraft,
    val creationKey: String,
)

internal class FakeIncomePlanCreateRepository(
    var active: IncomePlanListing = IncomePlanListing(emptyList(), 0L, month = "2026-09",
        scheduledAmountCents = 0, effectivePlanCount = 0, homeCurrencyCode = "CNY"),
    canModify: Boolean = true,
    var createResult: Result<Long>? = null,
) : IncomePlanActions {
    override val readAccessDenials = kotlinx.coroutines.flow.MutableSharedFlow<com.ticketbox.data.repository.SnapshotAccessDenial>()
    override suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?):
        Result<com.ticketbox.data.repository.ReadSnapshot<com.ticketbox.domain.model.IncomeHistoryPage>> = error("History is not requested in this fixture")

    val activeAccessFlow = MutableStateFlow<LedgerAccessContext?>(editAccess(canModify = canModify))
    val creationCalls = mutableListOf<IncomePlanCreateCall>()
    val lookups = mutableListOf<Pair<LogicalSessionBinding, String>>()
    var createResponder: (suspend (IncomePlanCreateCall) -> Result<Long>)? = null
    var lookupResponder: (suspend (LogicalSessionBinding, String) -> Result<PendingIncomePlanSubmission?>)? = null
    val originals = mutableMapOf<Pair<LogicalSessionBinding, String>, PendingIncomePlanSubmission>()
    val createCalls: Int get() = creationCalls.size
    val lastDraft: IncomePlanDraft? get() = creationCalls.lastOrNull()?.draft
    var listActiveCalls = 0

    override fun observeActiveLedgerAccess() = activeAccessFlow
    override fun describeSubmission(row: OutboxRow): PendingIncomePlanSubmission? = null
    override fun observeSubmissions(expectedBinding: LogicalSessionBinding) = flowOf(emptyList<PendingIncomePlanSubmission>())
    override suspend fun recoverSubmission(expectedBinding: LogicalSessionBinding,
        pending: PendingIncomePlanSubmission, drop: Boolean) = Result.success(Unit)
    override suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing> {
        listActiveCalls += 1
        return Result.success(active)
    }
    override suspend fun listIncluding(expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus): Result<com.ticketbox.data.repository.ReadSnapshot<List<IncomePlan>>> = Result.success(com.ticketbox.data.repository.ReadSnapshot(emptyList(), "2026-09-28T10:00:00Z", false))
    override suspend fun originalCreation(expectedBinding: LogicalSessionBinding,
        creationKey: String): Result<PendingIncomePlanSubmission?> {
        lookups += expectedBinding to creationKey
        return lookupResponder?.invoke(expectedBinding, creationKey) ?: Result.success(originals[expectedBinding to creationKey])
    }
    override suspend fun create(expectedBinding: LogicalSessionBinding, draft: IncomePlanDraft,
        creationKey: String): Result<Long> {
        val call = IncomePlanCreateCall(expectedBinding, draft, creationKey)
        creationCalls += call
        val result = createResponder?.invoke(call) ?: createResult ?: Result.success(1L)
        if (result.isSuccess) {
            originals[expectedBinding to creationKey] = createSubmission(call, result.getOrThrow())
        }
        return result
    }
    override suspend fun enqueueUpdate(expectedBinding: LogicalSessionBinding, baseline: IncomePlan,
        patch: IncomePlanPatch, currency: CurrencyCode): Result<Long> = error("Update belongs to the edit owner")
    override suspend fun archive(expectedBinding: LogicalSessionBinding, publicId: String,
        expectedRowVersion: Long, intentMonth: String): Result<IncomePlan> = error("Archive belongs to the edit owner")
    override suspend fun restore(expectedBinding: LogicalSessionBinding, publicId: String,
        expectedRowVersion: Long, intentMonth: String): Result<IncomePlan> = error("Restore belongs to the listing owner")
}

internal fun createSubmission(call: IncomePlanCreateCall, rowId: Long = 1,
    status: PendingMutationStatus = PendingMutationStatus.Pending): PendingIncomePlanSubmission {
    val draft = call.draft
    val intent = IncomePlanSubmissionPayload(2, "", draft.label, draft.amountCents, draft.homeCurrencyCode,
        call.binding.sessionGeneration, call.binding.bindingRevision,
        IncomePlanUpdateRequestDto(draft.intentMonth, 0, draft.label, draft.sourceType.wireValue,
            draft.frequency.wireValue, draft.incomeMonth, draft.amountCents, draft.payDay))
    val row = OutboxRow(rowId, call.binding.serverUrl, call.binding.ledgerId, call.binding.ownerKey,
        PendingMutationType.CreateIncomePlan, "income_plan_create:${call.creationKey}", "original-json", 0,
        status, 0, null, "2026-09-28T00:00:00Z", null, null, call.creationKey)
    return PendingIncomePlanSubmission(row, intent)
}

internal fun IncomePlanCreateViewModel.openOriginal(repo: FakeIncomePlanCreateRepository) {
    open(requireNotNull(repo.activeAccessFlow.value).binding, repo.active.month,
        CurrencyCode.fromStorageKeyOrNull(repo.active.homeCurrencyCode))
}
