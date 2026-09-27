package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import java.util.TimeZone
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RecurringHistoryReadTest {
    @Test fun externalGoalRefusalInvalidatesAnAlreadyRunningHistoryReadOnTheSameBinding() = runTest {
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?): RecurringHistoryPageDto {
                started.complete(Unit)
                release.await()
                return page()
            }
        } })
        val repository = RecurringRepository(fixture.provider, queryReader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        val reading = async { repository.history(fixture.binding, "recurring", null) }
        started.await()
        fixture.api.failure = HttpException(Response.error<Any>(403, "".toResponseBody()))
        assertTrue(fixture.repository.goal("goal-jpy").isFailure)
        release.complete(Unit)
        val failure = reading.await().exceptionOrNull() as RepositoryException
        assertEquals(403, failure.httpStatusCode)
        assertEquals(fixture.binding, fixture.coordinator.snapshotAccessDenials.value?.binding)
    }

    @Test fun historyRefusalPublishesTheSharedDenialAndRetiresExistingGoalReadPages() = runTest {
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?): RecurringHistoryPageDto =
                throw HttpException(Response.error<Any>(401, "".toResponseBody()))
        } })
        fixture.repository.goal("goal-jpy").getOrThrow()
        val repository = RecurringRepository(fixture.provider, queryReader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        assertTrue(repository.history(fixture.binding, "recurring", null).isFailure)
        assertEquals(401, fixture.coordinator.snapshotAccessDenials.value?.failure?.httpStatusCode)
        fixture.api.offline = true
        assertTrue(fixture.repository.goal("goal-jpy").isFailure)
    }

    @Test fun historyRejectsWrongLedgerIdOrderAndCursorWithoutChangingOriginalDefinition() = runTest {
        var response = page()
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?) = response
        } })
        val repository = RecurringRepository(fixture.provider, queryReader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        val originalTimezone = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Pacific/Honolulu"))
            assertEquals(page(), repository.history(fixture.binding, "recurring", null).getOrThrow().value)
        } finally { TimeZone.setDefault(originalTimezone) }
        val row = response.items.single()
        for (invalid in listOf(response.copy(ledgerId = "other"), response.copy(publicId = "other"),
            response.copy(items = listOf(row, row)), response.copy(nextBeforeVersion = 8))) {
            response = invalid
            assertTrue(repository.history(fixture.binding, "recurring", null).isFailure)
        }
        response = page()
        assertTrue(repository.history(fixture.binding, "recurring", 9).isFailure)
        val legacy = definition().copy(homeCurrencyCode = null, baselineAmountCents = 0, source = "candidate")
        response = response.copy(items = listOf(row.copy(snapshot = legacy)))
        assertEquals(legacy, repository.history(fixture.binding, "recurring", null).getOrThrow().value.items.single().snapshot)
    }

    @Test fun newLogicalSessionCannotAcceptALateOriginalHistoryResponse() = runTest {
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?): RecurringHistoryPageDto {
                started.complete(Unit)
                release.await()
                return page()
            }
        } })
        val repository = RecurringRepository(fixture.provider, queryReader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        val oldBinding = fixture.binding
        val reading = async { repository.history(oldBinding, "recurring", null) }
        started.await()
        fixture.session.clear()
        fixture.session.saveToken("replacement-session")
        release.complete(Unit)
        assertTrue(reading.await().isFailure)
    }

    @Test fun occurrenceWireKeepsFirstDefinitionSeparateFromCurrentPlanAndActualRecordedInstant() {
        val adapter = Moshi.Builder().build().adapter(RecurringOccurrenceDto::class.java)
        val body = """{"series_public_id":"recurring","period":"2026-09","series_row_version":9,"row_version":3,
            "state":"unfulfilled","planned_amount_cents":2400,"reserved_amount_cents":2400,
            "expense_public_id":null,"paid_amount_cents":null,"next_due_date":null,"home_currency_code":"JPY",
            "recorded_definition":{"series_row_version":7,"recorded_at":"2026-10-03T12:30:00Z",
            "snapshot":{"merchant":"原计划","merchant_key":"original","frequency":"monthly",
            "home_currency_code":"JPY","baseline_amount_cents":1200,"next_expected_date":"2026-09-09",
            "status":"active","source":"manual"}}}"""
        val occurrence = requireNotNull(adapter.fromJson(body))
        assertEquals(2400L, occurrence.plannedAmountCents)
        assertEquals(1200L, occurrence.recordedDefinition?.snapshot?.baselineAmountCents)
        assertEquals("2026-10-03T12:30:00Z", occurrence.recordedDefinition?.recordedAt)
        assertEquals("JPY", occurrence.recordedDefinition?.snapshot?.homeCurrencyCode)
        val relinked = occurrence.copy(rowVersion = 4, plannedAmountCents = 3600, expensePublicId = "replacement")
        assertEquals(occurrence.recordedDefinition, adapter.fromJson(adapter.toJson(relinked))?.recordedDefinition)
        val oldBody = body.substringBefore("\"recorded_definition\"").trimEnd().removeSuffix(",") + "}"
        assertNull(adapter.fromJson(oldBody)?.recordedDefinition)
    }

    private fun definition() = RecurringDefinitionDto("原计划", "original", "monthly", "JPY", 1200,
        "2026-10-09", "active", "manual")
    private fun page() = RecurringHistoryPageDto("owner", "recurring", listOf(RecurringRevisionDto(9, "edit",
        "2026-09-19T00:00:00Z", 1, definition())), 9)
}
