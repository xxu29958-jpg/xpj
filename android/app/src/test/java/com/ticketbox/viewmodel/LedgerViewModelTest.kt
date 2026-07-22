package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecentMerchant
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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

    @Test
    fun applyDrillFilterSetsMonthAndCategoryAtomicallyAndClearsTagQuery() = ledgerTest {
        // §三报表钻取:一次性落位(月, 分类),同时清 tag/query——残留旧搜索词会让
        // 明细对不上统计数字。
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setTagFilter("旅行")
        vm.setQuery("地铁")
        advanceUntilIdle()

        vm.applyDrillFilter(month = FIXTURE_MONTH, category = "餐饮")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(FIXTURE_MONTH, state.filter.monthFilter)
        assertEquals("餐饮", state.filter.categoryFilter)
        assertEquals("", state.filter.tagFilter)
        assertEquals("", state.filter.query)
        assertEquals(listOf(1L), state.items.map { it.id })
    }

    @Test
    fun exposesRecentMerchantsFromFullConfirmedCacheNewestFirst() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "早餐店")
                    .copy(expenseTime = "2026-05-01T08:00:00Z"),
                expense(id = 2, amountCents = 3000, category = "交通", merchant = "地铁")
                    .copy(expenseTime = "2026-05-09T08:00:00Z"),
                // Same merchant as #1 but newer + different category: the newest
                // occurrence supplies the slot and its category.
                expense(id = 3, amountCents = 1500, category = "夜宵", merchant = "早餐店")
                    .copy(expenseTime = "2026-05-10T08:00:00Z"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        // Recent merchants come from the WHOLE confirmed cache, independent of
        // the active month filter — narrowing the list mustn't drop suggestions.
        vm.setMonthFilter("2026-01")
        advanceUntilIdle()

        assertEquals(
            listOf(
                RecentMerchant(merchant = "早餐店", category = "夜宵"),
                RecentMerchant(merchant = "地铁", category = "交通"),
            ),
            vm.uiState.value.recentMerchants,
        )
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
        assertEquals(MessageTone.Success, state.messageTone)

        vm.manualCreateSettled()
        assertTrue(!vm.uiState.value.manualCreateDone)
    }

    @Test
    fun manualCreateOfflineSuccessShowsQueuedTruth() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
            manualCreate = ManualCreateBehavior(pendingSync = true),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        vm.createManualExpense(manualDraft())
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.manualCreateDone)
        assertEquals(UiText.res(R.string.ledger_msg_manual_saved_offline), state.message)
        assertEquals(MessageTone.Info, state.messageTone)
    }

    @Test
    fun manualCreateFailureKeepsSheetOpenWithInlineError() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
            // No exception message → toUiText falls through to the
            // screen-specific fallback resource asserted below.
            manualCreate = ManualCreateBehavior(failure = RuntimeException()),
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
    fun applyBatchSetsBatchDoneOnSuccessThenSettleClears() = ledgerTest {
        // batchDone is the one-shot signal the screen uses to close the sheet AFTER
        // the batch resolves (not eagerly) — set on success, cleared by batchSettled.
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        vm.applyBatchCategory("购物")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.batchDone)
        vm.batchSettled()
        assertTrue(!vm.uiState.value.batchDone)
    }

    @Test
    fun applyBatchFailureSetsBatchDoneAndKeepsSelection() = ledgerTest {
        // On a whole-batch failure the sheet must still close (batchDone) so the
        // page-level error message is visible; selection is preserved (only success
        // clears it) so the user can re-open the sheet and retry.
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
            batchFailure = RuntimeException("offline"),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        vm.applyBatchCategory("购物")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.batchDone)
        assertTrue(vm.uiState.value.selectionMode)
        assertEquals(setOf(1L), vm.uiState.value.selectedIds)
        // Pin the specific failure copy (toUiText carries the throwable message), not just non-null,
        // so a wrong/stale message resource on the failure arm is caught.
        assertEquals(UiText.raw("offline"), vm.uiState.value.message)
    }

    @Test
    fun applyBatchIgnoresReentryWhileInFlight() = ledgerTest {
        // Double-launch guard: a second apply while the first batch is in-flight must be ignored
        // (otherwise the second fan-out captures the same rowVersions and reports spurious OCC
        // failures). applyingBatch is set synchronously before the launch so the guard is effective.
        val gate = CompletableDeferred<Unit>()
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
            batchGate = gate,
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        vm.setMonthFilter(FIXTURE_MONTH)
        advanceUntilIdle()

        vm.enterSelection(1)
        vm.applyBatchCategory("购物") // launches; applyingBatch=true synchronously, awaits the gate
        runCurrent()
        assertTrue(vm.uiState.value.applyingBatch)

        vm.applyBatchCategory("购物") // re-entry while in-flight → guard returns, no second launch
        runCurrent()

        gate.complete(Unit)
        advanceUntilIdle()
        // Exactly one batch ran despite the second tap.
        assertEquals(1, fake.batchCallCount)
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
        // The empty-targets arm must also flip batchDone so the screen closes the sheet and the
        // page-level message is revealed (regression guard: the old eager close did this; the
        // batchDone-driven close would otherwise strand the sheet open over the message).
        assertTrue(vm.uiState.value.batchDone)
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

    // 8.4 — first-sync skeleton signal (pure LedgerUiState derivation) ------

    @Test
    fun isFirstSyncOnlyWhenEmptyAndSyncingAndNeverSyncedBefore() {
        // Fresh install: no cache, sync in flight, no prior sync timestamp.
        assertTrue(
            LedgerUiState(items = emptyList(), syncing = true, lastSyncAt = null).isFirstSync,
        )
    }

    @Test
    fun isFirstSyncFalseOncePreviouslySynced() {
        // Returning user (lastSyncAt set) refreshing an empty month: this is a
        // genuine empty state / pull-to-refresh, NOT the first-sync skeleton.
        assertFalse(
            LedgerUiState(
                items = emptyList(),
                syncing = true,
                lastSyncAt = "2026-05-17T10:00:00Z",
            ).isFirstSync,
        )
        assertFalse(
            LedgerUiState(
                items = emptyList(),
                syncing = true,
                syncedInCurrentSession = true,
            ).isFirstSync,
        )
    }

    @Test
    fun isFirstSyncFalseWhenItemsPresentOrNotSyncing() {
        // Has cached items while first sync runs → show the cache, not a skeleton.
        assertFalse(
            LedgerUiState(
                items = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
                syncing = true,
                lastSyncAt = null,
            ).isFirstSync,
        )
        // Idle + empty + never synced (e.g. first sync failed) → empty state, not skeleton.
        assertFalse(
            LedgerUiState(items = emptyList(), syncing = false, lastSyncAt = null).isFirstSync,
        )
    }

    @Test
    fun pageRefreshOnlyCoversUnreadLedger() {
        assertTrue(LedgerUiState(items = emptyList(), syncing = true).showPageRefresh)
        assertFalse(
            LedgerUiState(
                items = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
                syncing = true,
            ).showPageRefresh,
        )
        assertFalse(
            LedgerUiState(
                items = emptyList(),
                syncing = true,
                lastSyncAt = "2026-05-17T10:00:00Z",
            ).showPageRefresh,
        )
        assertFalse(
            LedgerUiState(
                items = emptyList(),
                syncing = true,
                syncedInCurrentSession = true,
            ).showPageRefresh,
        )
    }

    @Test
    fun duplicateSyncForSameFiltersIsCoalescedWhileInFlight() = ledgerTest {
        val fake = FakeLedgerActions(expenses = emptyList())
        val syncGate = CompletableDeferred<Unit>()
        fake.syncGate = syncGate

        val vm = LedgerViewModel(fake)
        runCurrent()
        assertEquals(1, fake.syncCallCount)

        vm.sync()
        runCurrent()
        assertEquals(1, fake.syncCallCount)

        syncGate.complete(Unit)
        advanceUntilIdle()
        vm.sync()
        advanceUntilIdle()
        assertEquals(2, fake.syncCallCount)
    }

    @Test
    fun monthsLoadStateSeparatesLoadingAndLoaded() = ledgerTest {
        val monthGate = CompletableDeferred<Unit>()
        val fake = FakeLedgerActions(expenses = emptyList()).apply {
            this.monthGate = monthGate
            monthResult = Result.success(listOf("2026-07", "2026-06"))
        }

        val vm = LedgerViewModel(fake)
        runCurrent()

        assertEquals(LedgerMonthsLoadState.Loading, vm.uiState.value.monthsLoadState)
        assertEquals(emptyList(), vm.uiState.value.months)

        monthGate.complete(Unit)
        advanceUntilIdle()

        assertEquals(LedgerMonthsLoadState.Loaded, vm.uiState.value.monthsLoadState)
        assertEquals(listOf("2026-07", "2026-06"), vm.uiState.value.months)
    }

    @Test
    fun monthsInitialFailureDoesNotLookLoadedEmpty() = ledgerTest {
        val fake = FakeLedgerActions(expenses = emptyList()).apply {
            monthResult = Result.failure(RuntimeException("months offline"))
        }

        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        assertEquals(LedgerMonthsLoadState.Failed, vm.uiState.value.monthsLoadState)
        assertEquals(emptyList(), vm.uiState.value.months)
    }

    @Test
    fun monthsRefreshFailureKeepsReadableMonths() = ledgerTest {
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A")),
        ).apply {
            monthResult = Result.success(listOf("2026-05"))
        }
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()
        assertEquals(LedgerMonthsLoadState.Loaded, vm.uiState.value.monthsLoadState)

        fake.monthResult = Result.failure(RuntimeException("months offline"))
        vm.createManualExpense(manualDraft())
        advanceUntilIdle()

        assertEquals(LedgerMonthsLoadState.Failed, vm.uiState.value.monthsLoadState)
        assertEquals(listOf("2026-05"), vm.uiState.value.months)
    }

    @Test
    fun exportCsvRefusesWhileDataQualityFilterActive() = ledgerTest {
        // The export endpoint only scopes by month/category/tag — under the
        // client-side data-quality filter an export would silently dump the
        // unfiltered scope, so the VM refuses with an explanation instead.
        val fake = FakeLedgerActions(
            expenses = listOf(expense(id = 1, amountCents = 1200, category = "未分类", merchant = "A")),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        vm.applyDataQualityFilter(LedgerDataQualityFilter.MissingCategory)
        advanceUntilIdle()
        vm.exportCsv()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(0, fake.exportCallCount)
        assertFalse(state.exporting)
        assertEquals(
            UiText.res(R.string.ledger_msg_export_data_quality_filter_active),
            state.message,
        )
        assertEquals(MessageTone.Info, state.messageTone)
    }

    @Test
    fun confirmedWithoutImageFilterReadsCacheImagePresence() = ledgerTest {
        // The Room cache drops image_path; the filter must read the stored
        // presence column, exactly like the backend's
        // image_path IS NULL OR image_deleted_at IS NOT NULL.
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "餐饮", merchant = "A").copy(hasImage = true),
                expense(id = 2, amountCents = 1300, category = "餐饮", merchant = "B"),
                expense(id = 3, amountCents = 1400, category = "餐饮", merchant = "C")
                    .copy(hasImage = true, imageDeletedAt = "2026-05-01T00:00:00Z"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        vm.applyDataQualityFilter(LedgerDataQualityFilter.ConfirmedWithoutImage)
        advanceUntilIdle()

        assertEquals(listOf(2L, 3L), vm.uiState.value.items.map { it.id })
    }

    @Test
    fun missingCategoryFilterSeesRawServerCategoryThroughNormalization() = ledgerTest {
        // Display-normalized 「其他」 must not hide a server-side blank category,
        // and a raw categorized value must not be misflagged either.
        val fake = FakeLedgerActions(
            expenses = listOf(
                expense(id = 1, amountCents = 1200, category = "其他", merchant = "A").copy(serverCategory = ""),
                expense(id = 2, amountCents = 1300, category = "其他", merchant = "B").copy(serverCategory = "餐饮"),
                expense(id = 3, amountCents = 1400, category = "未分类", merchant = "C"),
            ),
        )
        val vm = LedgerViewModel(fake)
        advanceUntilIdle()

        vm.applyDataQualityFilter(LedgerDataQualityFilter.MissingCategory)
        advanceUntilIdle()

        assertEquals(listOf(1L, 3L), vm.uiState.value.items.map { it.id })
    }
}

// Fixture expenses sit in 2026-05; tests pin monthFilter here so they stay
// passing as the wall-clock moves past that month.
private const val FIXTURE_MONTH = "2026-05"

private data class ManualCreateBehavior(
    val failure: Throwable? = null,
    val pendingSync: Boolean = false,
)

private class FakeLedgerActions(
    expenses: List<Expense>,
    private val canModify: Boolean = true,
    private val batchResult: BatchApplyResult? = null,
    private val batchFailure: Throwable? = null,
    /** When set, applyConfirmedBatch stalls until completed — used to interleave a re-tap. */
    private val batchGate: CompletableDeferred<Unit>? = null,
    private val manualCreate: ManualCreateBehavior = ManualCreateBehavior(),
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
    var syncCallCount = 0
        private set
    var exportCallCount = 0
        private set
    var syncGate: CompletableDeferred<Unit>? = null
    var monthResult: Result<List<String>> = Result.success(listOf("2026-05"))
    var monthGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override fun lastConfirmedSyncAt(): String? = "2026-05-17T10:00:00Z"

    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(confirmed)

    override suspend fun categories(): Result<List<String>> =
        Result.success(DEFAULT_EXPENSE_CATEGORIES)

    override suspend fun tags(): Result<List<String>> = Result.success(emptyList())

    override suspend fun months(): Result<List<String>> {
        monthGate?.await()
        return monthResult
    }

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> {
        syncCallCount++
        syncGate?.await()
        return Result.success(confirmed)
    }

    override suspend fun exportConfirmedCsv(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<CsvExport> {
        exportCallCount++
        return Result.success(CsvExport("ledger.csv", ByteArray(0)))
    }

    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> {
        manualCreate.failure?.let { return Result.failure(it) }
        val created = expense(
            id = if (manualCreate.pendingSync) {
                -((confirmed.maxOfOrNull { it.id } ?: 0L) + 1L)
            } else {
                (confirmed.maxOfOrNull { it.id } ?: 0L) + 1L
            },
            amountCents = draft.amountCents ?: 0L,
            category = draft.category ?: "其他",
            merchant = draft.merchant ?: "手动",
        ).copy(pendingSync = manualCreate.pendingSync)
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
        batchGate?.await()
        batchFailure?.let { return Result.failure(it) }
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
