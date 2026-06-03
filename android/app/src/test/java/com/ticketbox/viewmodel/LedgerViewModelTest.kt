package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
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
}

// Fixture expenses sit in 2026-05; tests pin monthFilter here so they stay
// passing as the wall-clock moves past that month.
private const val FIXTURE_MONTH = "2026-05"

private class FakeLedgerActions(
    expenses: List<Expense>,
    private val canModify: Boolean = true,
) : LedgerActions {
    private var confirmed = expenses

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
        val created = expense(
            id = (confirmed.maxOfOrNull { it.id } ?: 0L) + 1L,
            amountCents = draft.amountCents ?: 0L,
            category = draft.category ?: "其他",
            merchant = draft.merchant ?: "手动",
        )
        confirmed = confirmed + created
        return Result.success(created)
    }
}

private fun expense(
    id: Long,
    amountCents: Long,
    category: String,
    merchant: String,
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
