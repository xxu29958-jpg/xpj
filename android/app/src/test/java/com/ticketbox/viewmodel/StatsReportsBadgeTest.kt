package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepaymentDraftActions
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.RepaymentNotificationDraft
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

/**
 * 轨道2 [P1] 还款待确认 badge 计数管线：[StatsReportsViewModel] 在每次 refresh 时拉 pending 还款草稿数
 * （账本作用域，best-effort，代际守卫防跨账本回灌），经 [mergeStatsUiState] 不随月/标签 gate 地透传到
 * [StatsUiState.pendingRepaymentDraftCount]（菜单「还款待确认」项的 badge 源）。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class StatsReportsBadgeTest {

    private fun badgeTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshLoadsPendingDraftCount() = badgeTest {
        val drafts = FakeBadgeDrafts(Result.success(listOf(draft("a"), draft("b"), draft("c"))))
        val vm = StatsReportsViewModel(reportsRepository = null, repaymentDrafts = drafts)

        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        assertEquals(3, vm.uiState.value.pendingRepaymentDraftCount)
    }

    @Test
    fun countLoadsEvenWithoutReportsRepository() = badgeTest {
        // loadPendingDraftCount() 必须在 `reportsRepository ?: return` 早退之前运行——reportsRepository==null
        // 的构造点（部分测试 / 预览）仍要有 badge 计数。
        val drafts = FakeBadgeDrafts(Result.success(listOf(draft("a"))))
        val vm = StatsReportsViewModel(reportsRepository = null, repaymentDrafts = drafts)

        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        assertEquals(1, drafts.listCalls)
        assertEquals(1, vm.uiState.value.pendingRepaymentDraftCount)
    }

    @Test
    fun countLoadsRegardlessOfTagFilter() = badgeTest {
        // badge 是账本作用域：标签筛选态（reportsOverview 被清）下计数仍要拉，不被 tag gate 掉。
        val drafts = FakeBadgeDrafts(Result.success(listOf(draft("a"), draft("b"))))
        val vm = StatsReportsViewModel(reportsRepository = null, repaymentDrafts = drafts)

        vm.refresh(month = "2026-06", selectedTag = "餐饮")
        advanceUntilIdle()

        assertEquals(2, vm.uiState.value.pendingRepaymentDraftCount)
    }

    @Test
    fun countFailureKeepsLastKnownValue() = badgeTest {
        // best-effort badge：加载失败保留上次已知值，不因瞬时网络抖动把 badge 闪没。
        val drafts = FakeBadgeDrafts(Result.success(listOf(draft("a"), draft("b"))))
        val vm = StatsReportsViewModel(reportsRepository = null, repaymentDrafts = drafts)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        assertEquals(2, vm.uiState.value.pendingRepaymentDraftCount)

        drafts.listResult = Result.failure(RuntimeException("offline"))
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        assertEquals(2, vm.uiState.value.pendingRepaymentDraftCount)
    }

    @Test
    fun staleCountLoadDoesNotOverwriteNewer() = badgeTest {
        // 代际守卫 / 跨账本：账本 A 的慢计数加载被账本 B 的新加载超越后，A 落地时必须被丢弃，不回灌。
        val drafts = FakeBadgeDrafts(Result.success(listOf(draft("a1"), draft("a2"), draft("a3"))))
        val vm = StatsReportsViewModel(reportsRepository = null, repaymentDrafts = drafts)

        // 账本 A 的计数加载捕获 3 条后卡住（模拟慢 GET）。
        val gate = CompletableDeferred<Unit>()
        drafts.listGate = gate
        vm.refresh(month = "2026-06", selectedTag = "")
        runCurrent()

        // 账本 B 的计数加载（1 条）紧接着完成。
        drafts.listGate = null
        drafts.listResult = Result.success(listOf(draft("b1")))
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.pendingRepaymentDraftCount)

        // 放行 A 的慢加载：3 条不得回灌覆盖 B 的 1。
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.pendingRepaymentDraftCount)
    }

    @Test
    fun mergeCarriesPendingDraftCountUngatedByMonthAndTag() {
        // reports 面被月/标签 mismatch gate 掉（reportsOverview→null），但账本作用域 badge 计数仍要透传。
        val monthly = MonthlyStatsUiState(
            month = "2026-06",
            selectedTag = "餐饮",
            ledgerReady = true,
            activeLedgerId = "ledger-A",
        )
        val reports = StatsReportsUiState(
            month = "2026-05",
            selectedTag = "",
            pendingRepaymentDraftCount = 5,
        )

        val merged = mergeStatsUiState(monthly, StatsBudgetUiState(), reports)

        assertNull(merged.reportsOverview)
        assertEquals(5, merged.pendingRepaymentDraftCount)
    }

    @Test
    fun mergeDefaultsPendingDraftCountToZero() {
        val merged = mergeStatsUiState(MonthlyStatsUiState(), StatsBudgetUiState(), StatsReportsUiState())
        assertEquals(0, merged.pendingRepaymentDraftCount)
    }
}

private fun draft(id: String) = RepaymentDraft(
    publicId = id,
    source = "alipay",
    amountCents = 1_000L,
    homeCurrencyCode = "CNY",
    merchantLabel = null,
    capturedAt = "2026-06-19T00:00:00Z",
    status = RepaymentDraftStatuses.PENDING,
    committedDebtPublicId = null,
    committedRepaymentPublicId = null,
    createdAt = "2026-06-19T00:00:00Z",
    resolvedAt = null,
)

private class FakeBadgeDrafts(
    var listResult: Result<List<RepaymentDraft>> = Result.success(emptyList()),
) : RepaymentDraftActions {
    var listCalls = 0

    /** When set, listPendingDrafts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = true

    override suspend fun createDraft(
        draft: RepaymentNotificationDraft,
        expectedLedgerId: String?,
        notificationKey: String?,
    ): Result<RepaymentDraft> = Result.failure(UnsupportedOperationException())

    override suspend fun listPendingDrafts(): Result<List<RepaymentDraft>> {
        listCalls++
        // Capture at entry so a stalled load returns the snapshot it started with.
        val captured = listResult
        listGate?.await()
        return captured
    }

    override suspend fun confirmDraft(
        draftPublicId: String,
        targetDebtPublicId: String,
        expectedRowVersion: Long,
    ): Result<RepaymentDraft> = Result.failure(UnsupportedOperationException())

    override suspend fun dismissDraft(draftPublicId: String): Result<RepaymentDraft> =
        Result.failure(UnsupportedOperationException())
}
