package com.ticketbox.viewmodel

import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.ExpenseRevisionPage
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

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

    private fun revisionPage(page: Int, pageSize: Int, total: Int): ExpenseRevisionPage {
        val first = total - ((page - 1) * pageSize)
        val last = (first - pageSize + 1).coerceAtLeast(1)
        return ExpenseRevisionPage(
            items = (first downTo last).map(::revision),
            page = page,
            pageSize = pageSize,
            total = total,
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
