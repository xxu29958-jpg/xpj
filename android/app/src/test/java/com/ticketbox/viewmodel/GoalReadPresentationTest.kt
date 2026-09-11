package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class GoalReadPresentationTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() = Dispatchers.setMain(dispatcher)
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test
    fun cachedListAndDetailKeepCapturedCurrencyUnknownProgressAndReadTimeThenClearOnRefusal() = runTest(dispatcher) {
        val original = spendingGoal().copy(homeCurrencyCode = "JPY", spentAmountCents = null,
            remainingAmountCents = null, progressPercent = null)
        val reports = RecordingSpendingGoalActions(goalsResult = Result.success(listOf(original)),
            goalResult = Result.success(original)).apply { fromCache = true }
        val edits = RecordingGoalEdits()
        val list = SpendingGoalsViewModel(reports, edits, "2026-07")
        val detail = SpendingGoalDetailViewModel(reports, edits)
        try {
            detail.load(original.publicId)
            advanceUntilIdle()
            assertEquals("JPY", list.state.value.goals.single().homeCurrencyCode)
            assertNull(detail.state.value.goal?.progress)
            assertEquals(reports.fetchedAt, list.state.value.fetchedAt)
            assertEquals(reports.fetchedAt, detail.state.value.fetchedAt)
            assertTrue(detail.state.value.fromCache)
            reports.goalsResult = Result.failure(RepositoryException("Forbidden", httpStatusCode = 403))
            reports.goalResult = Result.failure(RepositoryException("Unauthorized", httpStatusCode = 401))
            list.refresh()
            detail.load()
            advanceUntilIdle()
            assertTrue(list.state.value.goals.isEmpty())
            assertNull(list.state.value.fetchedAt)
            assertNull(detail.state.value.goal)
            assertNull(detail.state.value.fetchedAt)
            assertTrue(edits.saves.isEmpty())
        } finally {
            list.viewModelScope.cancel()
            detail.viewModelScope.cancel()
        }
    }
}
