package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.SnapshotAccessDenial
import com.ticketbox.data.repository.DebtReadResourceDenial
import kotlinx.coroutines.flow.MutableSharedFlow
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtCreationActions
import com.ticketbox.data.repository.DebtCreationQueueSnapshot
import com.ticketbox.data.repository.DebtCreationReceipt
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.DebtSourceTypes
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow

// Shared fixtures for the DebtListViewModel test classes (split to stay inside the
// detekt class-size budget; mirrors GlobalSearchViewModelTestSupport).

internal class FakeDebtActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<Debt>> = Result.success(emptyList()),
    createResult: Result<Unit> = Result.success(Unit),
    var parseBillResult: Result<DebtBillSuggestion> = Result.success(blankBillSuggestion()),
) : DebtActions {
    val readDenials = MutableSharedFlow<SnapshotAccessDenial>()
    val resourceDenials = MutableSharedFlow<DebtReadResourceDenial>()
    override fun observeReadAccessDenials() = readDenials
    override fun observeResourceDenials() = resourceDenials
    var fromCache = false
    var detailResult = Result.success(sampleDebt())
    var detailGate: CompletableDeferred<Unit>? = null
    val creation = FakeDebtCreationActions(canModify, createResult)
    val writes = FakeDebtWriteActions(creation.access)
    val parseBillCalls = mutableListOf<String>()
    var listCalls = 0
    val listLenses = mutableListOf<DebtListLens>()

    /** When set, listDebts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null
    var parseBillGate: CompletableDeferred<Unit>? = null

    /** 列表信封的安装级 currency capability（PR#255 R6）；null = 旧服务端不下发。 */
    var listCapability: String? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(lens: DebtListLens): Result<ReadSnapshot<DebtListPage>> {
        listCalls++
        listLenses += lens
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps listResult in the meantime.
        val captured = listResult
        listGate?.await()
        return captured.map { ReadSnapshot(DebtListPage(debts = it, ledgerHomeCurrencyCode = listCapability), "2026-09-27T01:00:00Z", fromCache) }
    }

    override suspend fun getDebt(publicId: String): Result<ReadSnapshot<Debt>> {
        val captured = detailResult
        detailGate?.await()
        return captured.map { debtReadSnapshot(it.copy(publicId = publicId), fromCache) }
    }

    override suspend fun parseDebtBillImage(
        expectedBinding: LogicalSessionBinding,
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> {
        parseBillCalls += fileName
        val captured = parseBillResult
        parseBillGate?.await()
        return captured
    }



}

/** The creation boundary owns its binding, pending projection and controlled local acknowledgement. */
internal class FakeDebtCreationActions(
    canModify: Boolean,
    var createResult: Result<Unit>,
) : DebtCreationActions {
    val access = MutableStateFlow<LedgerAccessContext?>(
        LedgerAccessContext(LogicalSessionBinding("https://example.test", "owner", "test-owner", "session-1", "binding-1"), canModify),
    )
    val pendingCreations = MutableStateFlow(DebtCreationQueueSnapshot(access.value?.binding))
    val createDrafts = mutableListOf<DebtDraft>()
    var createGate: CompletableDeferred<Unit>? = null

    override fun currentAccess(): LedgerAccessContext? = access.value
    override fun observeActiveLedgerAccess() = access
    override fun observePendingCreations() = pendingCreations
    override fun describePendingCreation(row: OutboxRow): PendingDebtCreation? =
        pendingCreations.value.intents.singleOrNull { it.intentId == row.id }

    override suspend fun createDebt(
        expectedBinding: LogicalSessionBinding,
        draft: DebtDraft,
        homeCurrency: CurrencyCode,
    ): Result<DebtCreationReceipt> {
        createDrafts += draft
        val captured = createResult
        val receiptId = createDrafts.size.toLong()
        createGate?.await()
        return captured.map { DebtCreationReceipt(receiptId, expectedBinding) }
    }
}

internal fun blankBillSuggestion(): DebtBillSuggestion = DebtBillSuggestion(
    merchant = null,
    principalAmountCents = null,
    installmentCount = null,
    installmentPeriodMonths = null,
    perPeriodAmountCents = null,
    repaymentDay = null,
    sourceText = "",
    confidence = null,
)

internal fun sampleDebt(publicId: String = "debt-1"): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = 50_000,
    paidAmountCents = 0,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1,
)

internal fun <T> debtReadSnapshot(value: T, fromCache: Boolean = false) = ReadSnapshot(value, "2026-09-27T01:00:00Z", fromCache)
