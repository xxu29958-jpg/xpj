package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtCreationActions
import com.ticketbox.data.repository.DebtCreationQueueSnapshot
import com.ticketbox.data.repository.DebtCreationReceipt
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.DebtListPage
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
    var createResult: Result<Unit> = Result.success(Unit),
    var parseBillResult: Result<DebtBillSuggestion> = Result.success(blankBillSuggestion()),
) : DebtActions, DebtCreationActions {
    val access = MutableStateFlow<LedgerAccessContext?>(
        LedgerAccessContext(LogicalSessionBinding("https://example.test", "owner", "test-owner", "session-1", "binding-1"), canModify),
    )
    val pendingCreations = MutableStateFlow(DebtCreationQueueSnapshot(access.value?.binding))
    override fun currentAccess(): LedgerAccessContext? = access.value
    override fun observeActiveLedgerAccess() = access
    override fun observePendingCreations() = pendingCreations
    val createDrafts = mutableListOf<DebtDraft>()
    val parseBillCalls = mutableListOf<String>()
    var listCalls = 0
    val listLenses = mutableListOf<DebtListLens>()

    /** When set, listDebts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null

    /** Hold the command boundary while the real ViewModel receives another UI event. */
    var createGate: CompletableDeferred<Unit>? = null

    /** 列表信封的安装级 currency capability（PR#255 R6）；null = 旧服务端不下发。 */
    var listCapability: String? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(lens: DebtListLens): Result<DebtListPage> {
        listCalls++
        listLenses += lens
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps listResult in the meantime.
        val captured = listResult
        listGate?.await()
        return captured.map { DebtListPage(debts = it, ledgerHomeCurrencyCode = listCapability) }
    }

    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(sampleDebt(publicId))

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

    override suspend fun parseDebtBillImage(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> {
        parseBillCalls += fileName
        return parseBillResult
    }

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun voidRepayment(
        publicId: String,
        repaymentPublicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> = Result.failure(UnsupportedOperationException())

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun setDebtKind(
        publicId: String,
        expectedRowVersion: Long,
        debtKind: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))
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
