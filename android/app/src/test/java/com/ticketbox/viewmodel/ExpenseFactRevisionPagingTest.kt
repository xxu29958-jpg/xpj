package com.ticketbox.viewmodel

import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactRevisionPagingTest : ExpenseFactViewModelTestBase() {
    @Test
    fun `loading an older page appends until the earliest revision is reachable`() = edit { fake ->
        fake.revisionsResult = { page, pageSize ->
            Result.success(revisionPage(page = page, pageSize = pageSize, total = 51))
        }

        val viewModel = viewModel(fake)
        assertEquals(50, viewModel.uiState.value.revisions.size)
        assertEquals(2, viewModel.uiState.value.revisionsNextPage)

        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertEquals(51, state.revisions.size)
        assertEquals(1L, state.revisions.last().revisionNumber)
        assertEquals(51, state.revisionsTotal)
        assertNull(state.revisionsNextPage)
        assertFalse(state.revisionsOlderLoadFailed)
        assertEquals(listOf(1 to 50, 2 to 50), fake.revisionRequests)
    }

    @Test
    fun `snapshot anchor pins older paging until an explicit refresh`() = edit { fake ->
        // 锚=120 时 items/total 都必须属于 revision_number<=120 的前缀（冻结合同）。
        var serverSnapshot = 120L
        fake.revisionsResult = { page, pageSize ->
            Result.success(
                revisionPage(
                    page = page,
                    pageSize = pageSize,
                    total = serverSnapshot.toInt(),
                    snapshotRevision = serverSnapshot,
                ),
            )
        }

        val viewModel = viewModel(fake)
        assertEquals(120L, viewModel.uiState.value.revisionsSnapshotRevision)

        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        var state = viewModel.uiState.value
        assertEquals(120, state.revisions.size)
        assertEquals(1L, state.revisions.last().revisionNumber)
        assertNull(state.revisionsNextPage)
        // 首次进入不带锚；之后每一页都钉在服务端返回的同一快照上。
        assertEquals(listOf(null, 120L, 120L), fake.revisionSnapshots)

        serverSnapshot = 121L
        viewModel.loadExpenseRevisions()
        advanceUntilIdle()

        state = viewModel.uiState.value
        assertEquals(121L, state.revisionsSnapshotRevision)
        assertEquals(50, state.revisions.size)
        assertEquals(2, state.revisionsNextPage)

        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        // 显式刷新重新取锚（null → 121），随后 older 翻页继续钉新锚。
        assertEquals(listOf(null, 120L, 120L, null, 121L), fake.revisionSnapshots)
    }

    @Test
    fun `older page failure preserves loaded history and retry settles the same page`() = edit { fake ->
        var pageTwoAttempts = 0
        fake.revisionsResult = { page, pageSize ->
            if (page == 2 && pageTwoAttempts++ == 0) {
                Result.failure(IllegalStateException("offline"))
            } else {
                Result.success(revisionPage(page = page, pageSize = pageSize, total = 51))
            }
        }

        val viewModel = viewModel(fake)
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        assertEquals(50, viewModel.uiState.value.revisions.size)
        assertEquals(2, viewModel.uiState.value.revisionsNextPage)
        assertTrue(viewModel.uiState.value.revisionsOlderLoadFailed)

        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        assertEquals(51, viewModel.uiState.value.revisions.size)
        assertFalse(viewModel.uiState.value.revisionsOlderLoadFailed)
        assertEquals(listOf(1 to 50, 2 to 50, 2 to 50), fake.revisionRequests)
    }

    @Test
    fun `superseded older response cannot overwrite a newer first page`() = edit { fake ->
        fake.revisionsResult = { page, pageSize ->
            Result.success(revisionPage(page = page, pageSize = pageSize, total = 100))
        }
        val viewModel = viewModel(fake)
        val stalePageTwo = CompletableDeferred<Result<ExpenseRevisionPage>>()
        val freshPageOne = CompletableDeferred<Result<ExpenseRevisionPage>>()
        fake.revisionsResult = { page, _ ->
            when (page) {
                1 -> freshPageOne.await()
                2 -> stalePageTwo.await()
                else -> error("unexpected page $page")
            }
        }

        viewModel.loadOlderExpenseRevisions()
        runCurrent()
        viewModel.loadExpenseRevisions()
        runCurrent()
        freshPageOne.complete(Result.success(revisionPage(page = 1, pageSize = 50, total = 101)))
        runCurrent()
        stalePageTwo.complete(Result.success(revisionPage(page = 2, pageSize = 50, total = 100)))
        advanceUntilIdle()

        var state = viewModel.uiState.value
        assertEquals((101 downTo 52).map { it.toLong() }, state.revisions.map { it.revisionNumber })
        assertEquals(101, state.revisionsTotal)
        assertEquals(2, state.revisionsNextPage)

        fake.revisionsResult = { page, pageSize ->
            Result.success(revisionPage(page = page, pageSize = pageSize, total = 101))
        }
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        state = viewModel.uiState.value
        assertEquals((101 downTo 1).map { it.toLong() }, state.revisions.map { it.revisionNumber })
        assertNull(state.revisionsNextPage)
    }

    @Test
    fun `older paging cannot start while first page refresh is unsettled`() = edit { fake ->
        fake.revisionsResult = { page, pageSize ->
            Result.success(revisionPage(page = page, pageSize = pageSize, total = 100))
        }
        val viewModel = viewModel(fake)
        val freshPageOne = CompletableDeferred<Result<ExpenseRevisionPage>>()
        fake.revisionsResult = { page, pageSize ->
            if (page == 1) {
                freshPageOne.await()
            } else {
                Result.success(revisionPage(page = page, pageSize = pageSize, total = 102))
            }
        }

        viewModel.loadExpenseRevisions()
        viewModel.loadOlderExpenseRevisions()
        runCurrent()

        assertEquals(listOf(1 to 50, 1 to 50), fake.revisionRequests)

        freshPageOne.complete(Result.success(revisionPage(page = 1, pageSize = 50, total = 102)))
        advanceUntilIdle()
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertEquals((102 downTo 1).map { it.toLong() }, state.revisions.map { it.revisionNumber })
        assertNull(state.revisionsNextPage)
        assertEquals(listOf(1 to 50, 1 to 50, 2 to 50, 3 to 50), fake.revisionRequests)
    }

    @Test
    fun `first page refresh failure keeps loaded history and retry rebuilds paging`() = edit { fake ->
        fake.revisionsResult = { page, pageSize ->
            Result.success(revisionPage(page = page, pageSize = pageSize, total = 51))
        }
        val viewModel = viewModel(fake)
        viewModel.loadOlderExpenseRevisions()
        advanceUntilIdle()
        assertEquals(51, viewModel.uiState.value.revisions.size)

        fake.revisionsResult = { _, _ -> Result.failure(IllegalStateException("offline")) }
        viewModel.loadExpenseRevisions()
        advanceUntilIdle()

        var state = viewModel.uiState.value
        assertEquals(51, state.revisions.size)
        assertEquals(ExpenseDetailDataLoadState.Loaded, state.revisionsLoadState)
        assertTrue(state.revisionsRefreshFailed)
        assertNull(state.message)

        fake.revisionsResult = { page, pageSize ->
            Result.success(revisionPage(page = page, pageSize = pageSize, total = 52))
        }
        viewModel.loadExpenseRevisions()
        advanceUntilIdle()

        state = viewModel.uiState.value
        assertEquals(50, state.revisions.size)
        assertEquals(52, state.revisionsTotal)
        assertEquals(2, state.revisionsNextPage)
        assertFalse(state.revisionsRefreshFailed)
        assertNull(state.message)
    }

    @Test
    fun `initial revision failure retry success does not leave a stale page banner`() = edit { fake ->
        var shouldFail = true
        fake.revisionsResult = { page, pageSize ->
            if (shouldFail) {
                Result.failure(IllegalStateException("offline"))
            } else {
                Result.success(revisionPage(page = page, pageSize = pageSize, total = 1))
            }
        }
        val viewModel = viewModel(fake)

        assertEquals(ExpenseDetailDataLoadState.Failed, viewModel.uiState.value.revisionsLoadState)
        assertNull(viewModel.uiState.value.message)

        shouldFail = false
        viewModel.loadExpenseRevisions()
        advanceUntilIdle()

        assertEquals(ExpenseDetailDataLoadState.Loaded, viewModel.uiState.value.revisionsLoadState)
        assertNull(viewModel.uiState.value.message)
    }

    @Test
    fun `revision member labels consume the current directory without blocking history`() = edit { fake ->
        fake.splitMembersResult = {
            Result.success(listOf(fake.member(memberId = 7, displayName = "小明")))
        }

        val viewModel = viewModel(fake)

        assertEquals(mapOf(7L to "小明"), viewModel.uiState.value.revisionMemberNames)
    }

    @Test
    fun `member directory failure stays unknown instead of claiming every member was removed`() = edit { fake ->
        fake.splitMembersResult = { Result.failure(IllegalStateException("offline")) }

        val viewModel = viewModel(fake)

        assertNull(viewModel.uiState.value.revisionMemberNames)
        assertEquals(ExpenseDetailDataLoadState.Loaded, viewModel.uiState.value.revisionsLoadState)
    }

    private fun revisionPage(
        page: Int,
        pageSize: Int,
        total: Int,
        snapshotRevision: Long? = null,
    ): ExpenseRevisionPage {
        val first = total - ((page - 1) * pageSize)
        val last = (first - pageSize + 1).coerceAtLeast(1)
        return ExpenseRevisionPage(
            items = (first downTo last).map(::revision),
            page = page,
            pageSize = pageSize,
            total = total,
            // 默认锚=total：items/total 永远属于 revision_number<=锚 的合法前缀。
            snapshotRevision = snapshotRevision ?: total.toLong(),
        )
    }

    private fun revision(number: Int): ExpenseRevision = ExpenseRevision(
        publicId = "revision-$number",
        revisionNumber = number.toLong(),
        changeKind = if (number == 1) "confirmed" else "correction",
        reason = if (number == 1) "首次确认" else "更正 $number",
        changedFields = emptyList(),
        before = null,
        after = emptyMap(),
        actorAccountName = "我",
        actorDeviceName = "这台手机",
        createdAt = "2026-08-30T08:00:00Z",
    )
}
