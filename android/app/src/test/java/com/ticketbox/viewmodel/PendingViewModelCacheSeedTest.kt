package com.ticketbox.viewmodel

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * issue #64 A3：pending 列表本地优先读。验证 PendingViewModel 首屏 / 换账本时从
 * Room 缓存铺种子（消空白间隙）、飞行模式下缓存留守、下拉刷新不复活已清空的行。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelCacheSeedTest : PendingViewModelReviewTestBase() {

    @Test
    fun cachedPendingSeedsListBeforeNetworkThenFetchReplaces() = review {
        val networkResponse = CompletableDeferred<Result<List<com.ticketbox.domain.model.Expense>>>()
        val fake = FakeReviewActions()
        fake.cachedPending = listOf(expense(id = 1L, merchant = "Cached"))
        fake.fetchPendingResponder = { networkResponse.await() }

        val vm = PendingViewModel(fake)
        runCurrent()

        // 种子已铺：列表先显示缓存行，loading 仍 true（网络在飞）。
        assertEquals(listOf("Cached"), vm.uiState.value.items.map { it.merchant })
        assertTrue(vm.uiState.value.loading)

        networkResponse.complete(Result.success(listOf(expense(id = 2L, merchant = "Fresh"))))
        advanceUntilIdle()

        // 网络回来后整列替换为权威数据，loading 落下。
        assertEquals(listOf("Fresh"), vm.uiState.value.items.map { it.merchant })
        assertTrue(!vm.uiState.value.loading)
    }

    @Test
    fun airplaneModeKeepsCachedPendingWhenSyncFails() = review {
        val fake = FakeReviewActions()
        fake.cachedPending = listOf(expense(id = 1L, merchant = "Cached"))
        fake.fetchPendingResponder = { Result.failure(IOException("offline")) }

        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        // 飞行模式：缓存留在列表，网络失败只落 loading + 提示，不清空 items。
        assertEquals(listOf("Cached"), vm.uiState.value.items.map { it.merchant })
        assertTrue(!vm.uiState.value.loading)
        assertTrue(vm.uiState.value.message != null)
    }

    @Test
    fun pullToRefreshDoesNotResurrectClearedPendingFromCache() = review {
        // 红线守卫：缓存里仍有行，但服务端已无 pending（被别端确认/拒绝）。首屏种子
        // 短暂显示后被空响应替换；之后的下拉刷新绝不能再从陈旧缓存把行复活。
        val fake = FakeReviewActions()
        fake.cachedPending = listOf(expense(id = 1L, merchant = "Cached"))
        fake.pending = emptyList()

        val vm = PendingViewModel(fake)
        advanceUntilIdle()
        assertTrue(vm.uiState.value.items.isEmpty())

        vm.refresh()
        advanceUntilIdle()

        assertTrue(vm.uiState.value.items.isEmpty())
        // 关键守卫：首屏种子只读一次缓存；下拉刷新走 pendingCacheSeeded 闸不再回种。
        // 去掉闸后第二次 refresh 会再读一次缓存（getCachedPendingCalls==2）并在空响应
        // 替换前复活 [Cached] 一帧——本断言锁死「只种一次」，闸被删即红。
        assertEquals(1, fake.getCachedPendingCalls)
    }

    @Test
    fun emptyCacheFallsBackToNetworkFetch() = review {
        val fake = FakeReviewActions()
        fake.cachedPending = emptyList()
        fake.pending = listOf(expense(id = 1L, merchant = "Fresh"))

        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertEquals(listOf("Fresh"), vm.uiState.value.items.map { it.merchant })
    }
}
