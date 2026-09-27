package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.GoalQueryCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDefinitionDto
import com.ticketbox.data.remote.dto.GoalHistoryResponseDto
import com.ticketbox.data.remote.dto.GoalRevisionDto
import java.net.ConnectException
import java.util.TimeZone
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class GoalHistoryReadTest {
    @Test fun freshAuthorizedHistorySurvivesSqlitePublicationFailureButNeverInventsOfflineCache() = runTest {
        var offline = false
        var saveFailure: Throwable = SQLiteException("history cache is full")
        val fixture = historyFixture(decorateDao = { original -> object : ExpenseDao by original {
            override suspend fun saveGoalSnapshots(snapshots: List<GoalQueryCacheEntity>) { throw saveFailure }
        } }) { if (offline) throw ConnectException("offline") else page() }
        val fresh = fixture.repository.goalHistory("goal-jpy", null, fixture.binding).getOrThrow()
        assertFalse(fresh.fromCache)
        assertEquals(page().toDomain(), fresh.value)
        assertTrue(fresh.fetchedAt.isNotBlank())
        offline = true
        assertTrue(fixture.repository.goalHistory("goal-jpy", null, fixture.binding).isFailure)
        offline = false
        saveFailure = CancellationException("cancelled history publication")
        assertFailsWith<CancellationException> {
            fixture.repository.goalHistory("goal-jpy", null, fixture.binding)
        }
    }

    @Test fun readPageSurvivesDeviceTimezoneChangeReaderRecreationAndCredentialRefresh() = runTest {
        val originalTimezone = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Asia/Tokyo"))
            verifyReadPageAfterTimezoneChange()
        } finally {
            TimeZone.setDefault(originalTimezone)
        }
    }

    private suspend fun verifyReadPageAfterTimezoneChange() {
        var offline = false
        val fixture = historyFixture { if (offline) throw ConnectException("offline") else page() }
        val original = fixture.repository.goalHistory("goal-jpy", null, fixture.binding).getOrThrow()
        assertFalse(original.fromCache)
        fixture.session.saveToken("refreshed-token")
        TimeZone.setDefault(TimeZone.getTimeZone("Pacific/Honolulu"))
        offline = true
        val reopened = fixture.repository
        val saved = reopened.goalHistory("goal-jpy", null, fixture.binding).getOrThrow()
        assertTrue(saved.fromCache)
        assertEquals(original.value, saved.value)
        assertEquals(original.fetchedAt, saved.fetchedAt)
        assertEquals("JPY", saved.value.items.single().snapshot.homeCurrencyCode)
        assertEquals("2026-09-09T12:00:00Z", saved.value.items.single().recordedAt)
        assertTrue(reopened.goalHistory("goal-jpy", 9, fixture.binding).isFailure)
        assertTrue(reopened.goalHistory("never-read", null, fixture.binding).isFailure)
    }

    @Test fun wrongIdentityVersionOrderOrDefinitionNeverReplacesTheSavedOriginalPage() = runTest {
        var response = page()
        var offline = false
        val fixture = historyFixture { if (offline) throw ConnectException("offline") else response }
        val original = fixture.repository.goalHistory("goal-jpy", null, fixture.binding).getOrThrow()
        val row = response.items.single()
        val invalidPages = listOf(response.copy(ledgerId = "other-ledger"), response.copy(publicId = "other-goal"),
            response.copy(items = listOf(row, row)), response.copy(nextBeforeVersion = 8),
            response.copy(items = listOf(row.copy(rowVersion = 0))),
            response.copy(items = listOf(row.copy(snapshot = row.snapshot.copy(status = "archived"), changeKind = "restore"))),
            response.copy(items = listOf(row.copy(snapshot = row.snapshot.copy(goalType = "debt_repayment")))))
        invalidPages.forEach {
            response = it
            assertTrue(fixture.repository.goalHistory("goal-jpy", null, fixture.binding).isFailure)
        }
        response = page()
        assertTrue(fixture.repository.goalHistory("goal-jpy", 9, fixture.binding).isFailure)
        offline = true
        assertEquals(original.value, fixture.repository.goalHistory("goal-jpy", null, fixture.binding).getOrThrow().value)
    }

    @Test fun accessRefusalRetiresBothGoalAndHistoryCachesInsteadOfOfflineSuccess() = runTest {
        var error: Throwable? = null
        val fixture = historyFixture { error?.let { throw it }; page() }
        fixture.repository.goal("goal-jpy", timezone = "UTC").getOrThrow()
        fixture.repository.goalHistory("goal-jpy", null, fixture.binding).getOrThrow()
        error = HttpException(Response.error<Any>(403, "".toResponseBody()))
        assertTrue(fixture.repository.goalHistory("goal-jpy", 9, fixture.binding).isFailure)
        error = ConnectException("offline")
        fixture.api.offline = true
        assertTrue(fixture.repository.goal("goal-jpy", timezone = "UTC").isFailure)
        assertTrue(fixture.repository.goalHistory("goal-jpy", null, fixture.binding).isFailure)
    }

    @Test fun lateHistoryResponseCannotEnterANewLogicalSessionOrItsCache() = runTest {
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var offline = false
        val fixture = historyFixture {
            if (offline) throw ConnectException("offline")
            started.complete(Unit)
            release.await()
            page()
        }
        val old = fixture.binding
        val reading = async { fixture.repository.goalHistory("goal-jpy", null, old) }
        started.await()
        fixture.session.clear()
        fixture.session.saveToken("new-session")
        release.complete(Unit)
        assertTrue(reading.await().isFailure)
        offline = true
        assertTrue(fixture.repository.goalHistory("goal-jpy", null, fixture.binding).isFailure)
    }

    private fun historyFixture(decorateDao: (ExpenseDao) -> ExpenseDao = { it },
        respond: suspend () -> GoalHistoryResponseDto) = GoalReadFixture(decorateDao, decorate = { delegate ->
        object : ApiService by delegate {
            override suspend fun goalHistory(publicId: String, limit: Int, beforeVersion: Long?) = respond()
        }
    })

    private fun page() = GoalHistoryResponseDto("owner", "goal-jpy", listOf(GoalRevisionDto(9, "edit",
        "2026-09-09T12:00:00Z", GoalDefinitionDto("原计划", "spending_limit", "monthly", "2026-09",
            "旅行", 1200, "JPY", "active"))), 9)
}
