package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

/** W2-C 收入编辑测试共享夹具（IncomePlanEditViewModelTest / GuardsTest 同源）。 */
internal fun editPlan(
    id: String,
    amountCents: Long,
    status: IncomePlanStatus = IncomePlanStatus.ACTIVE,
    rowVersion: Long = 1L,
) = IncomePlan(
    publicId = id,
    label = "label-$id",
    sourceType = IncomeSourceType.SALARY,
    frequency = IncomeFrequency.MONTHLY,
    incomeMonth = null,
    amountCents = amountCents,
    payDay = 10,
    status = status,
    createdAt = "2026-05-01T00:00:00Z",
    updatedAt = "2026-05-01T00:00:00Z",
    rowVersion = rowVersion,
    archivedAt = if (status == IncomePlanStatus.ARCHIVED) "2026-05-15T00:00:00Z" else null,
)

internal data class IncomePlanUpdateCall(
    val binding: LogicalSessionBinding,
    val publicId: String,
    val patch: IncomePlanPatch,
)

internal data class IncomePlanArchiveCall(
    val binding: LogicalSessionBinding,
    val publicId: String,
    val rowVersion: Long,
)

internal class FakeIncomePlanEditRepository(
    var active: IncomePlanListing = IncomePlanListing(emptyList(), 0L),
    canModify: Boolean = true,
) : IncomePlanActions {
    val activeAccessFlow = MutableStateFlow<LedgerAccessContext?>(editAccess(canModify = canModify))
    val updateCalls = mutableListOf<IncomePlanUpdateCall>()
    val archiveCalls = mutableListOf<IncomePlanArchiveCall>()
    var updateResult: Result<IncomePlan>? = null
    var archiveResult: Result<IncomePlan>? = null

    /** 测试延迟钩：挂起 update 直至放行（模拟在途保存期间的 Back/手势/切 target）。 */
    var updateGate: (suspend () -> Unit)? = null

    override fun canModifyLedger(): Boolean = activeAccessFlow.value?.canModify ?: false

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = activeAccessFlow

    override suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing> =
        Result.success(active)

    override suspend fun listIncluding(
        expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus,
    ): Result<List<IncomePlan>> = Result.success(emptyList())

    override suspend fun create(
        expectedBinding: LogicalSessionBinding,
        draft: IncomePlanDraft,
    ): Result<IncomePlan> = throw UnsupportedOperationException("create not used in edit tests")

    override suspend fun update(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        patch: IncomePlanPatch,
    ): Result<IncomePlan> {
        updateCalls += IncomePlanUpdateCall(expectedBinding, publicId, patch)
        updateGate?.invoke()
        return updateResult ?: Result.success(
            IncomePlan(
                publicId = publicId,
                label = patch.label.orEmpty(),
                sourceType = patch.sourceType ?: IncomeSourceType.SALARY,
                frequency = patch.frequency ?: IncomeFrequency.MONTHLY,
                incomeMonth = patch.incomeMonth,
                amountCents = patch.amountCents ?: 0L,
                payDay = patch.payDay ?: 10,
                status = IncomePlanStatus.ACTIVE,
                createdAt = "2026-05-01T00:00:00Z",
                updatedAt = "2026-05-02T00:00:00Z",
                rowVersion = patch.expectedRowVersion + 1,
                archivedAt = null,
            ),
        )
    }

    override suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan> {
        archiveCalls += IncomePlanArchiveCall(expectedBinding, publicId, expectedRowVersion)
        return archiveResult ?: Result.success(
            IncomePlan(
                publicId = publicId,
                label = publicId,
                sourceType = IncomeSourceType.SALARY,
                frequency = IncomeFrequency.MONTHLY,
                incomeMonth = null,
                amountCents = 0L,
                payDay = 10,
                status = IncomePlanStatus.ARCHIVED,
                createdAt = "2026-05-01T00:00:00Z",
                updatedAt = "2026-05-02T00:00:00Z",
                rowVersion = expectedRowVersion + 1,
                archivedAt = "2026-05-15T00:00:00Z",
            ),
        )
    }

    override suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan> = throw UnsupportedOperationException("restore not used in edit tests")
}

internal fun editBinding(
    ledgerId: String = "owner",
    ownerKey: String = "owner",
): LogicalSessionBinding = LogicalSessionBinding(
    serverUrl = "https://api.example.com",
    ledgerId = ledgerId,
    ownerKey = ownerKey,
    sessionGeneration = "session-$ownerKey",
    bindingRevision = "binding-$ownerKey-$ledgerId",
)

internal fun editAccess(
    ledgerId: String = "owner",
    ownerKey: String = "owner",
    canModify: Boolean = true,
): LedgerAccessContext = LedgerAccessContext(
    binding = editBinding(ledgerId, ownerKey),
    canModify = canModify,
)
