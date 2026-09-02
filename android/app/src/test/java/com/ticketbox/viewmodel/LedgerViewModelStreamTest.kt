package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.StreamOffset
import com.ticketbox.domain.model.StreamOffsetKind
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import java.lang.reflect.Proxy
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Refund/Chargeback/Reversal 纵向片：LedgerViewModel 消费 typed confirmed
 * stream 的行为钉。金额只加 server-owned streamAmountCents（lineage net 永不
 * 进聚合）；选择/批量只达 expense root；月筛选读行自己的 streamDate
 * （offset 按自己的 accounting date 独立入流）。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LedgerViewModelStreamTest {
    private fun streamTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun summarySumsOnlyServerOwnedStreamContributions() = streamTest {
        val root = streamExpense(id = 1, amountCents = 12000, merchant = "超市")
        val reversedRoot = streamExpense(id = 2, amountCents = 8000, merchant = "误录")
        val fake = StreamLedgerActions(
            listOf(
                rootRow(root),
                refundRow(publicId = "off-1", root = root, streamDate = "2026-05-18", amountCents = 3000),
                rootRow(
                    reversedRoot,
                    streamAmountCents = 0L,
                    lineage = ExpenseLineageStatus.Reversed,
                ),
                reversalRow(publicId = "off-2", root = reversedRoot, streamDate = "2026-05-19"),
            ),
        )
        val vm = LedgerViewModel(fake, StreamDebtActions())
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_STREAM_MONTH)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(4, state.summary.itemCount)
        // 12000 - 3000 + 0 + 0：reversed root 的 gross 8000 与 reversal 事件都
        // 不再贡献；lineageHomeNetCents 绝不进页头聚合。
        assertEquals(9000L, state.summary.totalAmountCents)
    }

    @Test
    fun selectAllAndBatchReachExpenseRootsOnly() = streamTest {
        val root = streamExpense(id = 1, amountCents = 12000, merchant = "超市")
        val other = streamExpense(id = 2, amountCents = 5000, merchant = "地铁")
        val fake = StreamLedgerActions(
            listOf(
                rootRow(root),
                refundRow(publicId = "off-1", root = root, streamDate = "2026-05-18", amountCents = 3000),
                rootRow(other),
            ),
        )
        val vm = LedgerViewModel(fake, StreamDebtActions())
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_STREAM_MONTH)
        advanceUntilIdle()

        vm.selectAllVisible()
        // The offset event row contributes no checkbox and no batch target.
        assertEquals(setOf(1L, 2L), vm.uiState.value.selectedIds)

        vm.applyBatchCategory("购物", "统一整理")
        advanceUntilIdle()
        assertEquals(listOf(1L, 2L), fake.lastBatchExpenses.map { it.id })
    }

    @Test
    fun offsetRowFollowsItsOwnStreamDateNotRootMonth() = streamTest {
        val root = streamExpense(id = 1, amountCents = 12000, merchant = "超市")
        val fake = StreamLedgerActions(
            listOf(
                rootRow(root, streamDate = "2026-05-31"),
                refundRow(publicId = "off-1", root = root, streamDate = "2026-06-02", amountCents = 3000),
            ),
        )
        val vm = LedgerViewModel(fake, StreamDebtActions())
        advanceUntilIdle()

        vm.setMonthFilter("2026-06")
        advanceUntilIdle()
        assertEquals(listOf("offset-off-1"), vm.uiState.value.items.map { it.rowKey })

        vm.setMonthFilter(FIXTURE_STREAM_MONTH)
        advanceUntilIdle()
        assertEquals(listOf("expense-1"), vm.uiState.value.items.map { it.rowKey })
    }

    @Test
    fun dataQualityFiltersNeverMatchOffsetRows() = streamTest {
        // Root without an image matches the caliber; its refund event row must not.
        val root = streamExpense(id = 1, amountCents = 12000, merchant = "超市")
        val fake = StreamLedgerActions(
            listOf(
                rootRow(root),
                refundRow(publicId = "off-1", root = root, streamDate = "2026-05-18", amountCents = 3000),
            ),
        )
        val vm = LedgerViewModel(fake, StreamDebtActions())
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_STREAM_MONTH)
        advanceUntilIdle()

        vm.applyDataQualityFilter(LedgerDataQualityFilter.ConfirmedWithoutImage)
        advanceUntilIdle()
        assertEquals(listOf("expense-1"), vm.uiState.value.items.map { it.rowKey })
    }
}

private const val FIXTURE_STREAM_MONTH = "2026-05"

private class StreamLedgerActions(
    private val stream: List<ConfirmedStreamItem>,
) : LedgerActions {
    var lastBatchExpenses: List<Expense> = emptyList()
        private set

    override fun canModifyLedger(): Boolean = true

    override fun lastConfirmedSyncAt(): String? = "2026-05-17T10:00:00Z"

    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(stream.map { it.root }.distinctBy { it.id })

    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> = flowOf(stream)

    override suspend fun categories(): Result<List<String>> = Result.success(DEFAULT_EXPENSE_CATEGORIES)

    override suspend fun tags(): Result<List<String>> = Result.success(emptyList())

    override suspend fun months(): Result<List<String>> = Result.success(listOf("2026-05", "2026-06"))

    override suspend fun syncConfirmed(month: String?, category: String?, tag: String?): Result<List<Expense>> =
        Result.success(stream.map { it.root }.distinctBy { it.id })

    override suspend fun exportConfirmedCsv(month: String?, category: String?, tag: String?): Result<CsvExport> =
        Result.success(CsvExport("ledger.csv", ByteArray(0)))

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> =
        Result.failure(UnsupportedOperationException("manual create not used in stream tests"))

    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>,
        category: String?,
        tags: String?,
        reason: String,
    ): Result<BatchApplyResult> {
        lastBatchExpenses = expenses
        return Result.success(
            BatchApplyResult(
                requested = expenses.size,
                updated = expenses.size,
                skippedNotFound = 0,
                skippedNotConfirmed = 0,
            ),
        )
    }
}

private class StreamDebtActions : DebtActions by unsupportedStreamDebtActions() {
    override fun canModifyLedger(): Boolean = true

    override suspend fun listDebts(lens: com.ticketbox.domain.model.DebtListLens): Result<DebtListPage> =
        Result.success(DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "CNY"))
}

@Suppress("UNCHECKED_CAST")
private fun unsupportedStreamDebtActions(): DebtActions = Proxy.newProxyInstance(
    DebtActions::class.java.classLoader,
    arrayOf(DebtActions::class.java),
) { _, method, _ ->
    when (method.name) {
        "toString" -> "UnsupportedStreamDebtActions"
        else -> throw UnsupportedOperationException(method.name)
    }
} as DebtActions

private fun streamExpense(id: Long, amountCents: Long, merchant: String): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = amountCents,
    merchant = merchant,
    category = "餐饮",
    note = null,
    source = "manual",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = "2026-05-17T08:00:00Z",
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = "2026-05-17T08:01:00Z",
    rejectedAt = null,
)

private fun rootRow(
    root: Expense,
    streamDate: String = "2026-05-17",
    streamAmountCents: Long = root.amountCents ?: 0L,
    lineage: ExpenseLineageStatus = ExpenseLineageStatus.Confirmed,
) = ConfirmedStreamItem.ExpenseRow(
    streamDate = streamDate,
    streamAmountCents = streamAmountCents,
    root = root,
    lineageStatus = lineage,
    lineageHomeNetCents = streamAmountCents,
)

private fun refundRow(
    publicId: String,
    root: Expense,
    streamDate: String,
    amountCents: Long,
) = offsetRow(
    root = root,
    streamDate = streamDate,
    streamAmountCents = -amountCents,
    lineage = ExpenseLineageStatus.PartiallyRefunded,
    offset = streamOffset(publicId, StreamOffsetKind.Refund, amountCents),
)

private fun reversalRow(
    publicId: String,
    root: Expense,
    streamDate: String,
) = offsetRow(
    root = root,
    streamDate = streamDate,
    streamAmountCents = 0L,
    lineage = ExpenseLineageStatus.Reversed,
    offset = streamOffset(publicId, StreamOffsetKind.Reversal, amountCents = 0L),
)

private fun offsetRow(
    root: Expense,
    streamDate: String,
    streamAmountCents: Long,
    lineage: ExpenseLineageStatus,
    offset: StreamOffset,
) = ConfirmedStreamItem.OffsetRow(
    streamDate = streamDate,
    streamAmountCents = streamAmountCents,
    root = root,
    lineageStatus = lineage,
    lineageHomeNetCents = 0L,
    offset = offset,
)

private fun streamOffset(
    publicId: String,
    kind: StreamOffsetKind,
    amountCents: Long,
): StreamOffset = StreamOffset(
    publicId = publicId,
    kind = kind,
    amountCents = amountCents,
    originalAmountMinor = amountCents,
    originalCurrencyCode = "CNY",
    homeCurrencyCode = "CNY",
    category = "餐饮",
)
