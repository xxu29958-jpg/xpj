package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.UiText
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
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class LedgerViewModelTest {
    private fun ledgerTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun derivesSummaryFromFilteredItemsAndKeepsViewModeInState() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        // LedgerViewModel.monthFilter defaults to YearMonth.now() — pin to the
        // fixture's month so this test is date-independent (otherwise it would
        // pass in May 2026 and start failing in June when "2026-06" doesn't
        // match the fixture's "2026-05" expenseTime).
        vm.setMonthFilter(FIXTURE_MONTH)
        vm.setViewMode(LedgerViewMode.Table)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(LedgerViewMode.Table, state.viewMode)
        assertEquals(2, state.summary.itemCount)
        assertEquals(4200L, state.summary.totalAmountCents)
        assertTrue(state.filter.hasFilters)
    }

    @Test
    fun filtersItemsAndExposesFilterUi() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        // Same date-rollover guard as above.
        vm.setMonthFilter(FIXTURE_MONTH)
        vm.setCategoryFilter("餐饮")
        vm.setQuery("早餐")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(listOf(1L), state.items.map { it.id })
        assertEquals(1200L, state.summary.totalAmountCents)
        assertTrue(state.filter.hasFilters)
        assertEquals("餐饮", state.filter.categoryFilter)
        assertEquals("早餐", state.filter.query)
    }

    // ADR-0042 Slice C — multi-select + batch edit -------------------------

    @Test
    fun selectionModeTracksToggleAndSelectAll() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        assertTrue(vm.uiState.value.selectionMode)
        assertEquals(setOf(1L), vm.uiState.value.selectedIds)

        vm.toggleSelected(2)
        assertEquals(setOf(1L, 2L), vm.uiState.value.selectedIds)
        vm.toggleSelected(1)
        assertEquals(setOf(2L), vm.uiState.value.selectedIds)

        vm.selectAllVisible()
        assertEquals(setOf(1L, 2L), vm.uiState.value.selectedIds)

        vm.exitSelection()
        assertTrue(!vm.uiState.value.selectionMode)
        assertEquals(emptySet(), vm.uiState.value.selectedIds)
    }

    @Test
    fun applyBatchCategoryFansOutToSelectedExpenses() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        vm.toggleSelected(2)
        vm.applyBatchCategory("购物")
        advanceUntilIdle()

        assertEquals(1, fake.batchCallCount)
        assertEquals(setOf(1L, 2L), fake.lastBatchExpenses.map { it.id }.toSet())
        assertEquals("购物", fake.lastBatchCategory)
        assertEquals(null, fake.lastBatchTags)
        // selection clears on success; honest count message (per-clause
        // resourced via Compound now that the ledger surface renders it).
        assertTrue(!vm.uiState.value.selectionMode)
        assertEquals(emptySet(), vm.uiState.value.selectedIds)
        assertEquals(
            UiText.compound(listOf(UiText.res(R.string.ledger_msg_batch_part_synced, 2)), "，"),
            vm.uiState.value.message,
        )
    }

    @Test
    fun applyBatchTagsSendsTagsNotCategory() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店")),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        vm.applyBatchTags("出差")
        advanceUntilIdle()

        // The category column must NOT be touched by a tags-only batch.
        assertEquals("出差", fake.lastBatchTags)
        assertEquals(null, fake.lastBatchCategory)
    }

    @Test
    fun applyBatchReportsPartialSuccessHonestly() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A"),
                expense(id = 2, amountCents = 1200, category = "餐饮", merchant = "B"),
                expense(id = 3, amountCents = 1200, category = "餐饮", merchant = "C"),
            ),
            batchResult = BatchApplyResult(synced = 1, queued = 1, failed = 1),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.selectAllVisible()
        vm.applyBatchCategory("购物")
        advanceUntilIdle()

        // Per-clause resourced parts joined by Compound (ADR-0044): the
        // ledger surface now renders state.message, so the clauses must be
        // UiText.Res, not a pre-resolved Raw string.
        assertEquals(
            UiText.compound(
                listOf(
                    UiText.res(R.string.ledger_msg_batch_part_synced, 1),
                    UiText.res(R.string.ledger_msg_batch_part_queued, 1),
                    UiText.res(R.string.ledger_msg_batch_part_failed, 1),
                ),
                "，",
            ),
            vm.uiState.value.message,
        )
    }

    @Test
    fun manualCreateSuccessFlipsDoneForTheSheetToClose() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        vm.createManualExpense(manualDraft())
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.manualCreateDone)
        assertEquals(null, state.manualCreateError)
        assertEquals(UiText.res(R.string.ledger_msg_manual_saved), state.message)

        vm.manualCreateSettled()
        assertTrue(!vm.uiState.value.manualCreateDone)
    }

    @Test
    fun manualCreateFailureKeepsSheetOpenWithInlineError() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
            // No exception message → toUiText falls through to the
            // screen-specific fallback resource asserted below.
            manualCreateFailure = RuntimeException(),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        vm.createManualExpense(manualDraft())
        advanceUntilIdle()

        val state = vm.uiState.value
        // done must NOT flip (the sheet stays open, preserving the typed
        // form); the failure surfaces through the sheet-inline channel.
        assertTrue(!state.manualCreateDone)
        assertEquals(UiText.res(R.string.ledger_msg_manual_save_failed), state.manualCreateError)
        assertTrue(!state.creatingManual)

        vm.manualCreateSettled()
        assertEquals(null, vm.uiState.value.manualCreateError)
    }

    @Test
    fun applyBatchBlockedWhenReadOnly() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
            canModify = false,
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        vm.applyBatchCategory("购物")
        advanceUntilIdle()

        assertEquals(0, fake.batchCallCount)
        assertEquals(UiText.res(R.string.common_readonly_ledger), vm.uiState.value.message)
    }

    @Test
    fun applyBatchWithoutSelectionPrompts() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.applyBatchCategory("购物")
        advanceUntilIdle()

        assertEquals(0, fake.batchCallCount)
        assertEquals(UiText.res(R.string.ledger_msg_batch_no_selection), vm.uiState.value.message)
    }

    @Test
    fun selectAllVisibleRespectsActiveFilter() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        vm.setCategoryFilter("餐饮")
        advanceUntilIdle()

        vm.selectAllVisible()
        // Only the visible (filtered) row is selected — not the whole dataset.
        assertEquals(setOf(1L), vm.uiState.value.selectedIds)
    }

    @Test
    fun selectedHaveTagsTracksFullSelectionNotFilteredView() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店", tags = "出差"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        assertTrue(vm.uiState.value.selectedHaveTags)

        // Narrow the filter so the tagged row leaves the visible list — the
        // replace-gate flag must stay true (keyed off allConfirmed, not the
        // filtered view), so the destructive-replace confirm can't be bypassed.
        vm.setCategoryFilter("交通")
        advanceUntilIdle()
        assertTrue(vm.uiState.value.selectedHaveTags)
    }
}

// Fixture expenses sit in 2026-05; tests pin monthFilter here so they stay
// passing as the wall-clock moves past that month.
private const val FIXTURE_MONTH = "2026-05"

private class FakeLedgerActions(
    expenses: List<Expense>,
    private val canModify: Boolean = true,
    private val batchResult: BatchApplyResult? = null,
    private val manualCreateFailure: Throwable? = null,
) : LedgerActions {
    private var confirmed = expenses

    var batchCallCount = 0
        private set
    var lastBatchExpenses: List<Expense> = emptyList()
        private set
    var lastBatchCategory: String? = null
        private set
    var lastBatchTags: String? = null
        private set

    override fun canModifyLedger(): Boolean = canModify

    override fun lastConfirmedSyncAt(): String? = "2026-05-17T10:00:00Z"

    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(confirmed)

    override suspend fun categories(): Result<List<String>> =
        Result.success(DEFAULT_EXPENSE_CATEGORIES)

    override suspend fun tags(): Result<List<String>> = Result.success(emptyList())

    override suspend fun months(): Result<List<String>> = Result.success(listOf("2026-05"))

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = Result.success(confirmed)

    override suspend fun exportConfirmedCsv(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<CsvExport> = Result.success(CsvExport("ledger.csv", ByteArray(0)))

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> {
        manualCreateFailure?.let { return Result.failure(it) }
        val created = expense(
            id = (confirmed.maxOfOrNull { it.id } ?: 0L) + 1L,
            amountCents = draft.amountCents ?: 0L,
            category = draft.category ?: "其他",
            merchant = draft.merchant ?: "手动",
        )
        confirmed = confirmed + created
        return Result.success(created)
    }

    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>,
        category: String?,
        tags: String?,
    ): Result<BatchApplyResult> {
        batchCallCount++
        lastBatchExpenses = expenses
        lastBatchCategory = category
        lastBatchTags = tags
        return Result.success(batchResult ?: BatchApplyResult(synced = expenses.size))
    }
}

private fun manualDraft(): ExpenseDraft = ExpenseDraft(
    amountCents = 990L,
    merchant = "手动店",
    category = "餐饮",
    note = null,
    expenseTime = "2026-05-17T09:00:00Z",
    tags = null,
    valueScore = null,
    regretScore = null,
)

private fun expense(
    id: Long,
    amountCents: Long,
    category: String,
    merchant: String,
    tags: String? = null,
): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = amountCents,
    merchant = merchant,
    category = category,
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
    tags = tags,
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
