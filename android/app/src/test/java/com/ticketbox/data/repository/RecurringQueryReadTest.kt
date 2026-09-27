package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import java.net.ConnectException
import java.util.TimeZone
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class RecurringQueryReadTest {
    @Test fun recreatedReadersKeepOriginalReadTimeCurrencyAndPeriodWithoutMakingRemindersOrAdviceFresh() = runTest {
        lateinit var api: RecurringReadProbe
        val fixture = GoalReadFixture(decorate = { RecurringReadProbe(it).also { probe -> api = probe } })
        fun repository() = RecurringRepository(fixture.provider, queryReader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator))
        val repository = repository()
        var stamps = 0
        repository.onFullItemsSnapshot = { stamps++ }
        val items = repository.items(fixture.binding, includeArchived = true).getOrThrow()
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val history = reader.history(fixture.binding, "recurring", null).getOrThrow()
        val period = reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
        assertEquals(1, stamps)
        api.failure = ConnectException("offline")
        val recreated = repository().also { it.onFullItemsSnapshot = { stamps++ } }
        assertEquals(items.copy(fromCache = true), recreated.items(fixture.binding, includeArchived = true).getOrThrow())
        val oldTimezone = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Pacific/Honolulu"))
            val reopened = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            assertEquals(history.copy(fromCache = true), reopened.history(fixture.binding, "recurring", null).getOrThrow())
            assertEquals(period.copy(fromCache = true), reopened.occurrence(fixture.binding, "recurring", "current").getOrThrow())
            assertEquals(period.copy(fromCache = true), reopened.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
            assertEquals("2026-09", period.value.period)
            assertTrue(reopened.occurrence(fixture.binding, "recurring", "2026-08").isFailure)
            assertTrue(reopened.history(fixture.binding, "recurring", 9).isFailure)
        } finally { TimeZone.setDefault(oldTimezone) }
        assertTrue(recreated.items().isFailure, "The reminder source cannot use a UI read cache")
        assertEquals(1, stamps, "A cached full list is not a new advisor input snapshot")
    }

    @Test fun storagePublicationFailureKeepsFreshGetButRefusalOrMalformedResponseNeverUsesOldCache() = runTest {
        lateinit var api: RecurringReadProbe
        val saved = FakeExpenseDao()
        var failWrites = false
        val dao = object : ExpenseDao by saved {
            override suspend fun saveRecurringSnapshotIfCurrent(snapshot: StatsProjectionCacheEntity, expectedEpoch: Long) {
                if (failWrites) throw SQLiteException("projection unavailable")
                saved.saveRecurringSnapshotIfCurrent(snapshot, expectedEpoch)
            }
        }
        val fixture = GoalReadFixture(decorateDao = { dao }, decorate = { RecurringReadProbe(it).also { probe -> api = probe } })
        val reader = RecurringQueryReader(fixture.provider, dao, fixture.coordinator)
        reader.items(fixture.binding, null, true, null).getOrThrow()
        failWrites = true
        api.item = api.item.copy(baselineAmountCents = 3600)
        val fresh = reader.items(fixture.binding, null, true, null).getOrThrow()
        assertFalse(fresh.fromCache)
        assertEquals(3600L, fresh.value.single().baselineAmountCents)
        api.item = api.item.copy(ledgerId = "another-ledger")
        assertTrue(reader.items(fixture.binding, null, true, null).isFailure)
        api.failure = HttpException(Response.error<Any>(403, "".toResponseBody()))
        assertTrue(reader.items(fixture.binding, null, true, null).isFailure)
        api.failure = ConnectException("offline after refusal")
        assertTrue(RecurringQueryReader(fixture.provider, dao, fixture.coordinator).items(fixture.binding, null, true, null).isFailure)
    }

    @Test fun acceptedCommandInAnotherQueryOwnerChangesDurableEpochAndRejectsAnEarlierGet() = runTest {
        lateinit var api: RecurringReadProbe
        val fixture = GoalReadFixture(decorate = { RecurringReadProbe(it).also { probe -> api = probe } })
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        api.started = CompletableDeferred()
        api.release = CompletableDeferred()
        val reading = async { reader.items(fixture.binding, null, true, null) }
        requireNotNull(api.started).await()
        RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator).invalidate(fixture.binding)
        requireNotNull(api.release).complete(Unit)
        assertTrue(reading.await().isFailure)
        assertEquals("1", fixture.dao.recurringReadEpoch(logicalBindingAdapter.toJson(fixture.binding)))
    }

    @Test fun acceptedPauseSurvivesCacheFailureButCannotPublishItsEarlierActiveRead() = runTest {
        lateinit var api: RecurringReadProbe
        var failInvalidation = false
        val saved = FakeExpenseDao()
        val dao = object : ExpenseDao by saved {
            override suspend fun settleRecurringDirectBarrier(bindingKey: String, ledgerId: String, token: String,
                accepted: Boolean, expectedEpoch: Long?) {
                if (failInvalidation) throw SQLiteException("storage temporarily unavailable")
                saved.settleRecurringDirectBarrier(bindingKey, ledgerId, token, accepted, expectedEpoch)
            }
        }
        val fixture = GoalReadFixture(decorateDao = { dao }, decorate = { delegate ->
            api = RecurringReadProbe(delegate)
            object : ApiService by api {
                override suspend fun pauseRecurringItem(publicId: String,
                    request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto {
                    assertEquals("recurring", publicId)
                    assertEquals(9L, request.expectedRowVersion)
                    return api.item.copy(status = "paused", rowVersion = 10)
                }
            }
        })
        val repository = RecurringRepository(fixture.provider, queryReader = RecurringQueryReader(fixture.provider, dao, fixture.coordinator))
        repository.items(fixture.binding, includeArchived = true).getOrThrow()
        api.started = CompletableDeferred()
        api.release = CompletableDeferred()
        val older = async { repository.items(fixture.binding, includeArchived = true) }
        requireNotNull(api.started).await()
        failInvalidation = true
        val accepted = repository.pause(fixture.binding, "recurring", 9).getOrThrow()
        assertEquals("paused", accepted.status)
        requireNotNull(api.release).complete(Unit)
        assertTrue(older.await().isFailure, "The accepted pause cannot be undone by a late active read, even when Room invalidation failed")
        api.failure = ConnectException("offline after accepted pause")
        assertTrue(repository.items(fixture.binding, includeArchived = true).isFailure)
        val cold = RecurringQueryReader(fixture.provider, dao,
            LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, dao))
        assertTrue(cold.items(fixture.binding, null, true, null).isFailure,
            "Rebuilding the owner cannot resurrect the active RV9 after an accepted pause and failed Room cleanup")
        failInvalidation = false
        api.failure = null
        api.item = api.item.copy(status = "paused", rowVersion = 10)
        val repaired = repository.items(fixture.binding, includeArchived = true).getOrThrow()
        assertEquals("paused", repaired.value.single().status)
        api.failure = ConnectException("offline after verified read")
        assertEquals(repaired.copy(fromCache = true), repository.items(fixture.binding, includeArchived = true).getOrThrow())
    }

    @Test fun definitivelyRejectedPauseKeepsAlreadyReadListHistoryAndOccurrenceAfterReentry() = runTest {
        lateinit var api: RecurringReadProbe
        val fixture = GoalReadFixture(decorate = { delegate ->
            api = RecurringReadProbe(delegate)
            object : ApiService by api {
                override suspend fun pauseRecurringItem(publicId: String,
                    request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto =
                    throw HttpException(Response.error<Any>(409, "".toResponseBody()))
            }
        })
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val repository = RecurringRepository(fixture.provider, queryReader = reader)
        val list = reader.items(fixture.binding, null, true, null).getOrThrow()
        val history = reader.history(fixture.binding, "recurring", null).getOrThrow()
        val occurrence = reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
        assertTrue(repository.pause(fixture.binding, "recurring", 9).isFailure)
        api.failure = ConnectException("offline after definite rejection")
        val cold = RecurringQueryReader(fixture.provider, fixture.dao,
            LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, fixture.dao))
        assertEquals(list.copy(fromCache = true), cold.items(fixture.binding, null, true, null).getOrThrow())
        assertEquals(history.copy(fromCache = true), cold.history(fixture.binding, "recurring", null).getOrThrow())
        assertEquals(occurrence.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "current").getOrThrow())
        assertEquals(null, fixture.dao.recurringReadEpoch(logicalBindingAdapter.toJson(fixture.binding)))
    }

    @Test fun unresolvedDirectDispatchBlocksAnotherWriterAndOldReadsUntilActualFreshGet() = runTest {
        lateinit var api: RecurringReadProbe
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var calls = 0
        val fixture = GoalReadFixture(decorate = { delegate ->
            api = RecurringReadProbe(delegate)
            object : ApiService by api {
                override suspend fun pauseRecurringItem(publicId: String,
                    request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto {
                    calls++
                    started.complete(Unit)
                    release.await()
                    throw ConnectException("response lost after dispatch")
                }
            }
        })
        fun reader() = RecurringQueryReader(fixture.provider, fixture.dao,
            LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, fixture.dao))
        fun repository() = RecurringRepository(fixture.provider, queryReader = reader())
        val original = repository()
        original.items(fixture.binding, includeArchived = true).getOrThrow()
        val dispatch = async { original.pause(fixture.binding, "recurring", 9) }
        started.await()
        val token = fixture.dao.recurringDirectBarrier(logicalBindingAdapter.toJson(fixture.binding))
        assertTrue(reader().items(fixture.binding, null, true, null).isFailure, "A GET during dispatch cannot consume its barrier")
        assertTrue(repository().pause(fixture.binding, "recurring", 9).isFailure)
        assertEquals(token, fixture.dao.recurringDirectBarrier(logicalBindingAdapter.toJson(fixture.binding)))
        reader().invalidate(fixture.binding)
        assertEquals(token, fixture.dao.recurringDirectBarrier(logicalBindingAdapter.toJson(fixture.binding)),
            "An accepted Outbox invalidation must not remove another executing direct command's barrier")
        release.complete(Unit)
        assertTrue(dispatch.await().isFailure)
        assertEquals(1, calls, "Unresolved non-idempotent commands must never be resent by cache recovery")
        api.failure = ConnectException("offline after unknown result")
        assertTrue(reader().items(fixture.binding, null, true, null).isFailure)
        api.failure = null
        api.item = api.item.copy(status = "paused", rowVersion = 10)
        val verified = reader().items(fixture.binding, null, true, null).getOrThrow()
        assertEquals("paused", verified.value.single().status)
        api.failure = ConnectException("offline after reconciliation")
        assertEquals(verified.copy(fromCache = true), reader().items(fixture.binding, null, true, null).getOrThrow())
        assertEquals(1, calls)
    }

    @Test fun candidateRefusalRevokesCachedPagesAndLateItemsBeforeColdOfflineReentry() = runTest {
        for (status in listOf(401, 403)) {
            lateinit var api: RecurringReadProbe
            val fixture = GoalReadFixture(decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun recurringCandidates(timezone: String?): com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto =
                        throw HttpException(Response.error<Any>(status, "".toResponseBody()))
                }
            })
            val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            val repository = RecurringRepository(fixture.provider, queryReader = reader)
            repository.items(fixture.binding, includeArchived = true).getOrThrow()
            reader.history(fixture.binding, "recurring", null).getOrThrow()
            reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
            api.started = CompletableDeferred()
            api.release = CompletableDeferred()
            val late = async { repository.items(fixture.binding, includeArchived = true) }
            requireNotNull(api.started).await()
            assertTrue(repository.candidates(fixture.binding).isFailure)
            assertEquals(status, fixture.coordinator.snapshotAccessDenials.value?.failure?.httpStatusCode)
            requireNotNull(api.release).complete(Unit)
            assertTrue(late.await().isFailure, "A candidate refusal must block an earlier complete list from returning")
            api.failure = ConnectException("cold offline after candidate refusal")
            val cold = RecurringQueryReader(fixture.provider, fixture.dao,
                LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, fixture.dao))
            assertTrue(cold.items(fixture.binding, null, true, null).isFailure)
            assertTrue(cold.history(fixture.binding, "recurring", null).isFailure)
            assertTrue(cold.occurrence(fixture.binding, "recurring", "current").isFailure)
        }
    }

    @Test fun newerCurrentPaymentAndSameVersionReviewStateRemainVisibleWhenOfflineChoosingItsExplicitMonth() = runTest {
        var offline = false
        var response = RecurringOccurrenceDto("recurring", "2026-09", 9, 0, "unfulfilled", 2400, 2400, null, null, null,
            homeCurrencyCode = "JPY")
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
                if (offline) throw ConnectException("offline period")
                return response
            }
        } })
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        response = response.copy(rowVersion = 1, state = "fulfilled", reservedAmountCents = 0,
            expensePublicId = "paid-original", paidAmountCents = 2400, paidHomeCurrencyCode = "JPY")
        val paid = reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
        offline = true
        val cold = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        assertEquals(paid.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
        offline = false
        reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        response = response.copy(state = "needs_review")
        val reviewed = reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
        offline = true
        assertEquals(reviewed.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
        assertTrue(cold.occurrence(fixture.binding, "recurring", "2026-08").isFailure)
    }

    @Test fun lateCurrentReadCannotReplaceNewerExplicitPeriodAndOfflineNeverInventsAnotherMonth() = runTest {
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var offline = false
        val earlier = RecurringOccurrenceDto("recurring", "2026-09", 9, 0, "unfulfilled", 2400, 2400, null, null, null,
            homeCurrencyCode = "JPY")
        val newer = earlier.copy(seriesRowVersion = 10, plannedAmountCents = 3600, reservedAmountCents = 3600)
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
                if (offline) throw ConnectException("offline period")
                if (month != "current") return newer
                started.complete(Unit)
                release.await()
                return earlier
            }
        } })
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val current = async { reader.occurrence(fixture.binding, "recurring", "current") }
        started.await()
        val explicit = reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        release.complete(Unit)
        current.await().getOrThrow()
        offline = true
        val reopened = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        assertEquals(explicit.copy(fromCache = true), reopened.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
        assertTrue(reopened.occurrence(fixture.binding, "recurring", "2026-08").isFailure)
    }

}

internal class RecurringReadProbe(delegate: ApiService) : ApiService by delegate {
    var item = recurringReadItem()
    var failure: Throwable? = null
    var started: CompletableDeferred<Unit>? = null
    var release: CompletableDeferred<Unit>? = null
    override suspend fun recurringItems(status: String?, includeArchived: Boolean, month: String?, timezone: String?): RecurringItemListResponseDto {
        failure?.let { throw it }
        started?.complete(Unit)
        release?.await()
        return RecurringItemListResponseDto(listOf(item))
    }
    override suspend fun recurringHistory(publicId: String, limit: Int, beforeVersion: Long?): RecurringHistoryPageDto {
        failure?.let { throw it }
        return RecurringHistoryPageDto("owner", publicId, listOf(RecurringRevisionDto(9, "edit", "2026-09-19T12:30:00Z", null, definition())), 9)
    }
    override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
        failure?.let { throw it }
        return RecurringOccurrenceDto(publicId, "2026-09", 9, 0, "unfulfilled", 2400, 2400, null, null, "2026-10-09", homeCurrencyCode = "JPY")
    }
    private fun definition() = RecurringDefinitionDto("原安排", "original", "monthly", "JPY", 1200, "2026-09-09", "active", "manual")
}

internal fun recurringReadItem() = RecurringItemDto(publicId = "recurring", ledgerId = "owner", merchant = "原计划",
    merchantKey = "original", frequency = "monthly", baselineAmountCents = 2400, lastAmountCents = 1200,
    occurrenceCount = 0, lastSeenAt = null, nextExpectedDate = "2026-10-09", status = "active", confidence = null,
    source = "manual", createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-20T00:00:00Z", rowVersion = 9,
    pausedAt = null, archivedAt = null, nextDueDate = "2026-10-09", homeCurrencyCode = "JPY")
