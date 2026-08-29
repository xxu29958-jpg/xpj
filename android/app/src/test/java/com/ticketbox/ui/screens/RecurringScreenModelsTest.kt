package com.ticketbox.ui.screens

import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.ui.screens.recurring.RecurringTab
import com.ticketbox.ui.screens.recurring.recurringDefaultTab
import com.ticketbox.ui.screens.recurring.recurringHasReadableData
import com.ticketbox.ui.screens.recurring.recurringHeroModel
import com.ticketbox.ui.screens.recurring.recurringScreenDerived
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** 屏级派生：列表 bodyState、hero 总额、默认/筛选 tab、可读性判定。 */
class RecurringScreenModelsTest {

    @Test
    fun bodyStateSeparatesUnknownLoadingFailureEmptyAndContent() {
        assertEquals(
            ReadableListBodyState.Loading,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Unknown),
        )
        assertEquals(
            ReadableListBodyState.Loading,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Loading),
        )
        assertEquals(
            ReadableListBodyState.LoadFailed,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Failed),
        )
        assertEquals(
            ReadableListBodyState.Empty,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Loaded),
        )
        assertEquals(
            ReadableListBodyState.Content,
            recurringListBodyState(hasRows = true, loadState = RecurringListLoadState.Failed),
        )
    }

    @Test
    fun heroSumsOnlyActivePublishedBaseline() {
        val items = listOf(
            recurringItem { publicId = "a"; status = "active"; baselineAmountCents = 300_00; nextExpectedDate = "2026-09-15" },
            recurringItem { publicId = "b"; status = "active"; baselineAmountCents = 120_00; nextExpectedDate = "2026-09-01" },
            recurringItem { publicId = "c"; status = "paused"; baselineAmountCents = 999_00 },
            recurringItem { publicId = "d"; status = "archived"; baselineAmountCents = 888_00 },
        )
        val hero = recurringHeroModel(items, RecurringListLoadState.Loaded)
        assertEquals(true, hero.factual)
        assertEquals(420_00, hero.totalCents)
        assertEquals(2, hero.activeCount)
        assertEquals("2026-09-01", hero.nearestNextDate)
    }

    @Test
    fun heroIsNotFactualUntilLoadedOrCached() {
        val unknown = recurringHeroModel(emptyList(), RecurringListLoadState.Unknown)
        assertEquals(false, unknown.factual)
        val failed = recurringHeroModel(emptyList(), RecurringListLoadState.Failed)
        assertEquals(false, failed.factual)
        val loaded = recurringHeroModel(emptyList(), RecurringListLoadState.Loaded)
        assertEquals(true, loaded.factual)
        assertEquals(0L, loaded.totalCents)
        assertNull(loaded.nearestNextDate)
    }

    @Test
    fun heroNeverCountsPendingIntents() {
        val state = RecurringUiState(
            items = listOf(
                recurringItem { publicId = "a1"; status = "active"; baselineAmountCents = 300_00 },
            ),
            pendingIntents = listOf(
                RecurringPendingIntent(
                    kind = RecurringPendingKind.CREATE,
                    targetId = "local-1",
                    idempotencyKey = "key-1",
                    merchant = "待同步项",
                    baselineAmountCents = 999_00,
                ),
            ),
            itemsLoadState = RecurringListLoadState.Loaded,
        )
        val hero = recurringScreenDerived(state, RecurringTab.Upcoming).hero
        assertEquals(300_00, hero.totalCents)
        assertEquals(1, hero.activeCount)
    }

    @Test
    fun defaultTabIsActiveSoDatelessNewItemStaysVisible() {
        // 无提醒日期的新建固定支出保存后必须留在默认列表；Upcoming 只是快捷筛选。
        assertEquals(RecurringTab.Active, recurringDefaultTab)
    }

    @Test
    fun durablePendingCountsAsReadableData() {
        val pendingOnly = RecurringUiState(
            pendingIntents = listOf(
                RecurringPendingIntent(
                    kind = RecurringPendingKind.CREATE,
                    targetId = "local-1",
                    idempotencyKey = "key-1",
                    merchant = "宽带",
                ),
            ),
        )
        assertEquals(true, recurringHasReadableData(pendingOnly))
        assertEquals(false, recurringHasReadableData(RecurringUiState()))
        assertEquals(
            true,
            recurringHasReadableData(RecurringUiState(items = listOf(recurringItem()))),
        )
    }

    @Test
    fun upcomingTabIsActiveWithDateAndCountsMatchRealSets() {
        val state = RecurringUiState(
            items = listOf(
                recurringItem { publicId = "a1"; status = "active"; nextExpectedDate = "2026-09-01" },
                recurringItem { publicId = "a2"; status = "active"; nextExpectedDate = null },
                recurringItem { publicId = "a3"; status = "active"; nextExpectedDate = "2026-08-30" },
                recurringItem { publicId = "p1"; status = "paused"; nextExpectedDate = "2026-09-01" },
                recurringItem { publicId = "x1"; status = "archived"; nextExpectedDate = "2026-09-01" },
            ),
            itemsLoadState = RecurringListLoadState.Loaded,
        )
        val upcoming = recurringScreenDerived(state, RecurringTab.Upcoming)
        // 即将 = active 且 nextExpectedDate 非空，按日期排；无日期 active 只留在活跃。
        assertEquals(listOf("a3", "a1"), upcoming.itemSection.rows.map { it.publicId })
        assertEquals(2, upcoming.counts.upcoming)
        assertEquals(3, upcoming.counts.active)
        assertEquals(1, upcoming.counts.paused)
        assertEquals(1, upcoming.counts.archived)
        val active = recurringScreenDerived(state, RecurringTab.Active)
        assertEquals(3, active.itemSection.rows.size)
    }
}
