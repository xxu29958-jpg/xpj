package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import java.net.ConnectException
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
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

internal class RecurringQueryReadTest : ExpensePendingRepositoryOutboxTestBase() {
    private val readClock = Clock.fixed(Instant.parse("2026-10-10T01:00:00Z"), ZoneOffset.UTC)
    @Test fun cachedPayloadCannotReturnAfterAnotherOwnerRetiresItBetweenReadAndDecode() = runTest {
        lateinit var api: RecurringReadProbe
        var afterCacheRead: (suspend () -> Unit)? = null
        val saved = FakeExpenseDao()
        val dao = object : ExpenseDao by saved {
            override suspend fun recurringSnapshotIfCurrent(query: StatsProjectionCacheEntity, expectedEpoch: Long): StatsProjectionCacheEntity? {
                val payload = saved.recurringSnapshotIfCurrent(query, expectedEpoch)
                val after = afterCacheRead
                afterCacheRead = null
                after?.invoke()
                return payload
            }
        }
        val fixture = GoalReadFixture(decorateDao = { dao }, decorate = { RecurringReadProbe(it).also { probe -> api = probe } })
        val reader = RecurringQueryReader(fixture.provider, dao, fixture.coordinator)
        reader.history(fixture.binding, "recurring", null).getOrThrow()
        api.failure = ConnectException("offline cache read")
        afterCacheRead = { RecurringQueryReader(fixture.provider, dao, fixture.coordinator).invalidate(fixture.binding) }
        assertTrue(reader.history(fixture.binding, "recurring", null).isFailure,
            "A payload already fetched from Room cannot escape after a different owner's accepted mutation retired its epoch")
    }

    @Test fun directCredentialRevocationPersistsReadDenialButWriteOnlyForbiddenKeepsReadFacts() = runTest {
        for (status in listOf(401, 403)) {
            lateinit var api: RecurringReadProbe
            val settings = boundSettingsStore()
            val saved = FakeExpenseDao()
            val dao = object : ExpenseDao by saved {
                override suspend fun clearReadSnapshotsForBinding(bindingKey: String) {
                    throw SQLiteException("denied read cleanup unavailable")
                }
            }
            val fixture = GoalReadFixture(decorateDao = { dao }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun pauseRecurringItem(publicId: String,
                        request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest): RecurringItemDto =
                        throw HttpException(Response.error<Any>(status, "".toResponseBody()))
                }
            })
            val coordinator = LocalLedgerSessionCoordinator(settings, fixture.session.sessionStore, dao)
            val reader = RecurringQueryReader(fixture.provider, dao, coordinator)
            val original = reader.items(fixture.binding, null, true, null).getOrThrow()
            assertTrue(RecurringRepository(fixture.provider, queryReader = reader).pause(fixture.binding, "recurring", 9).isFailure)
            api.failure = ConnectException("offline after direct refusal")
            val cold = RecurringQueryReader(fixture.provider, dao,
                LocalLedgerSessionCoordinator(settings, fixture.session.sessionStore, dao))
            val reopened = cold.items(fixture.binding, null, true, null)
            if (status == 401) {
                assertEquals(401, coordinator.snapshotAccessDenials.value?.failure?.httpStatusCode)
                assertEquals(401, (reopened.exceptionOrNull() as RepositoryException).httpStatusCode,
                    "The retained payload cannot resurrect after owner reconstruction and credential revocation")
            } else {
                assertEquals(null, coordinator.snapshotAccessDenials.value)
                assertEquals(original.copy(fromCache = true), reopened.getOrThrow(), "A write-only 403 is not read revocation")
            }
        }
    }

    @Test fun originalOutboxCredentialRefusalPersistsReadDenialButWriteOnly403KeepsReadFacts() = runTest {
        for ((status, rebindBeforeResponse) in listOf(401 to false, 403 to false, 401 to true)) {
            lateinit var api: RecurringReadProbe
            var beforeRefusal: () -> Unit = {}
            val settings = boundSettingsStore()
            val saved = FakeExpenseDao()
            val dao = object : ExpenseDao by saved {
                override suspend fun clearReadSnapshotsForBinding(bindingKey: String) {
                    throw SQLiteException("denied read cleanup unavailable")
                }
            }
            val fixture = GoalReadFixture(decorateDao = { dao }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun updateRecurringItem(publicId: String, request: RecurringItemUpdateRequestDto,
                        idempotencyKey: String): RecurringItemDto {
                        beforeRefusal()
                        throw HttpException(Response.error<Any>(status, "".toResponseBody()))
                    }
                }
            })
            val coordinator = LocalLedgerSessionCoordinator(settings, fixture.session.sessionStore, dao)
            val reader = RecurringQueryReader(fixture.provider, dao, coordinator)
            val original = reader.items(fixture.binding, null, true, null).getOrThrow()
            val pending = FakePendingMutationDao()
            val outbox = testOutboxRepository(pending, bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            outbox.onRecurringDispatchPreparing = reader::prepareDispatch
            outbox.onRecurringDispatchFinished = reader::finishDispatch
            outbox.onRecurringAccepted = reader::invalidateAccepted
            val adapters = OutboxAdapterGraph()
            val repository = RecurringRepository(fixture.provider, outbox, adapters, queryReader = reader)
            repository.updateAllowingOffline(fixture.binding, original.value.single(),
                RecurringItemPatch(merchant = "原编辑", homeCurrencyCode = requireNotNull(original.value.single().homeCurrencyCode))).getOrThrow()
            val row = pending.allRows().single()
            val guard = LedgerRequestGuard(fixture.provider)
            val engine = OutboxDrainEngine(outbox, listOf(UpdateRecurringItemDispatcher({ request ->
                guard.bind(expectedLedgerId = request.ledgerId).serviceFor(requireNotNull(request.bindingOrNull()))
            }, adapters.recurringUpdateAdapter)))
            if (rebindBeforeResponse) beforeRefusal = {
                fixture.session.rebindToDifferentServerForFixture("https://other.example.com", "other-session-token")
            }
            assertEquals(1, engine.drainOnce().failures)
            val failed = pending.allRows().single()
            assertEquals(row.idempotencyKey, failed.idempotencyKey)
            assertEquals(row.payload, failed.payload)
            assertEquals(row.expectedRowVersion, failed.expectedRowVersion)
            api.failure = ConnectException("cold offline after original HTTP refusal")
            val cold = RecurringQueryReader(fixture.provider, dao,
                LocalLedgerSessionCoordinator(settings, fixture.session.sessionStore, dao))
            val reopened = cold.items(fixture.binding, null, true, null)
            if (rebindBeforeResponse) {
                assertEquals(null, coordinator.snapshotAccessDenials.value,
                    "An old request's 401 cannot revoke the replacement identity's read access")
                assertTrue((reopened.exceptionOrNull() as RepositoryException).httpStatusCode != 401)
            } else if (status == 401) {
                assertEquals(401, coordinator.snapshotAccessDenials.value?.failure?.httpStatusCode)
                assertEquals(401, (reopened.exceptionOrNull() as RepositoryException).httpStatusCode)
            } else {
                assertEquals(null, coordinator.snapshotAccessDenials.value)
                assertEquals(original.copy(fromCache = true), reopened.getOrThrow())
            }
        }
    }

    @Test fun acceptedManualExpenseRetiresTheOldAmountAnomalyUntilItsActualCurrentList() = runTest {
        lateinit var api: RecurringReadProbe
        val request = ExpenseManualCreateRequestDto(originalCurrency = "JPY", originalAmount = "3600", spentAt = null,
            merchant = "原计划", category = "其他", note = null, expenseTime = "2026-09-21T12:00:00Z", tags = null,
            valueScore = null, regretScore = null, clientRef = "original-manual-ref", homeCurrencyCode = "JPY")
        val receipt = successExpenseDto().copy(merchant = request.merchant, homeCurrency = "JPY", originalCurrencyCode = "JPY",
            originalAmountMinor = 3600, amountCents = 3600, source = "手动记账", status = "confirmed")
        var calls = 0
        var published = 0
        var refusal: HttpException? = null
        val fixture = GoalReadFixture(decorate = { delegate ->
            api = RecurringReadProbe(delegate)
            object : ApiService by api {
                override suspend fun createManualExpense(submitted: ExpenseManualCreateRequestDto): ExpenseDto {
                    assertEquals(request, submitted)
                    refusal?.let { throw it }
                    calls++
                    api.item = api.item.copy(anomalyStatus = "higher_than_average", currentMonthAmountCents = 3600)
                    return receipt
                }
            }
        })
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val original = reader.items(fixture.binding, null, true, null).getOrThrow()
        assertEquals("none", original.value.single().anomalyStatus)
        val pending = FakePendingMutationDao()
        val outbox = testOutboxRepository(pending, bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
        outbox.onRecurringDispatchPreparing = reader::prepareDispatch
        outbox.onRecurringDispatchFinished = reader::finishDispatch
        outbox.onRecurringAccepted = reader::invalidateAccepted
        val adapter = moshi().adapter(ExpenseManualCreateRequestDto::class.java)
        val guard = LedgerRequestGuard(fixture.provider)
        val dispatcher = CreateExpenseDispatcher({ row ->
            guard.bind(expectedLedgerId = row.ledgerId).serviceFor(requireNotNull(row.bindingOrNull()))
        }, adapter, applyServerIdentity = { ledger, ref, created ->
            assertEquals(fixture.binding.ledgerId, ledger)
            assertEquals(request.clientRef, ref)
            assertEquals(receipt, created)
            published++
        })
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        val malformedId = outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:malformed", "{}", 0,
            idempotencyKey = "malformed-original-key")
        assertEquals(1, engine.drainOnce().failures)
        assertEquals(0, calls, "Malformed original never reaches the create provider")
        api.failure = ConnectException("offline after an unsent original")
        assertEquals(original.copy(fromCache = true), reader.items(fixture.binding, null, true, null).getOrThrow())
        assertTrue(outbox.resolveFailed(malformedId, FailedResolution.Drop))
        val refusedId = outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:original-manual-ref", adapter.toJson(request), 0,
            idempotencyKey = "refused-create-key")
        refusal = HttpException(Response.error<Any>(422, "invalid original".toResponseBody()))
        assertEquals(1, engine.drainOnce().failures)
        assertEquals(0, calls)
        assertEquals(original.copy(fromCache = true), reader.items(fixture.binding, null, true, null).getOrThrow(),
            "A definite create refusal preserves this month's known amount anomaly")
        assertTrue(outbox.resolveFailed(refusedId, FailedResolution.Drop))
        refusal = null
        api.failure = null
        outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:original-manual-ref", adapter.toJson(request), 0,
            idempotencyKey = "original-create-key")
        val originalRow = pending.allRows().single()
        assertEquals(1, engine.drainOnce().done)
        val done = pending.allRows().single()
        assertEquals("done", done.status)
        assertEquals(originalRow.payload, done.payload)
        assertEquals(originalRow.idempotencyKey, done.idempotencyKey)
        assertEquals(1, calls)
        assertEquals(1, published)
        api.failure = ConnectException("cold offline after confirmed manual create")
        val cold = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        assertTrue(cold.items(fixture.binding, null, true, null).isFailure,
            "A confirmed create changes this month's amount anomaly even when it does not edit the Recurring series")
        api.failure = null
        val fresh = cold.items(fixture.binding, null, true, null).getOrThrow()
        assertEquals("higher_than_average", fresh.value.single().anomalyStatus)
        assertEquals(3600L, fresh.value.single().currentMonthAmountCents)
        api.failure = ConnectException("offline after current anomaly query")
        assertEquals(fresh.copy(fromCache = true), cold.items(fixture.binding, null, true, null).getOrThrow())
    }

    @Test fun acceptedLinkedExpenseChangesRetireListAndOccurrenceUntilTheirActualGet() = runTest {
        val types = listOf(PendingMutationType.PatchExpense, PendingMutationType.CorrectExpense,
            PendingMutationType.ConfirmExpense, PendingMutationType.UndoExpense,
            PendingMutationType.CreateExpenseOffset, PendingMutationType.VoidExpenseOffset)
        for (mutationType in types) {
            lateinit var api: RecurringReadProbe
            val initiallyInvalid = mutationType in setOf(PendingMutationType.ConfirmExpense, PendingMutationType.UndoExpense,
                PendingMutationType.VoidExpenseOffset)
            var period = RecurringOccurrenceDto("recurring", "2026-09", 9, 1,
                if (initiallyInvalid) "needs_review" else "fulfilled", 2400, if (initiallyInvalid) 2400 else 0,
                "payment-original", if (initiallyInvalid) null else 2400,
                if (initiallyInvalid) "2026-09-09" else "2026-10-09", expenseId = 1, homeCurrencyCode = "JPY", paidHomeCurrencyCode = if (initiallyInvalid) null else "JPY")
            val fixture = GoalReadFixture(decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
                        api.failure?.let { throw it }
                        return period
                    }
                }
            })
            val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            reader.items(fixture.binding, null, true, null).getOrThrow()
            reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
            reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
            val pending = FakePendingMutationDao()
            val outbox = testOutboxRepository(pending, bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            outbox.onRecurringDispatchPreparing = reader::prepareDispatch
            outbox.onRecurringDispatchFinished = reader::finishDispatch
            outbox.onRecurringAccepted = reader::invalidateAccepted
            val id = outbox.enqueue(mutationType, "expense:1", "{}", 3, idempotencyKey = "original-key")
            // Dispatcher acceptance is the boundary; drain settlement and both GET/cache consumers are real.
            val dispatcher = object : OutboxMutationDispatcher {
                override val type = mutationType
                override suspend fun dispatch(row: OutboxRow): DispatchResult {
                    assertEquals("original-key", row.idempotencyKey)
                    assertEquals("{}", row.payloadJson)
                    assertEquals(3L, row.expectedRowVersion)
                    period = if (mutationType == PendingMutationType.CreateExpenseOffset) period.copy(state = "needs_review",
                        reservedAmountCents = 2400, paidAmountCents = null, paidHomeCurrencyCode = null, nextDueDate = "2026-09-09")
                    else period.copy(state = "fulfilled", reservedAmountCents = 0, paidAmountCents = 3600, paidHomeCurrencyCode = "JPY", nextDueDate = "2026-10-09")
                    api.item = api.item.copy(nextDueDate = period.nextDueDate)
                    return DispatchResult.Success(newRowVersion = 4)
                }
            }
            assertEquals(1, OutboxDrainEngine(outbox, listOf(dispatcher)).drainOnce().done)
            assertEquals("done", pending.allRows().single { it.id == id }.status)
            api.failure = ConnectException("cold offline after accepted $mutationType")
            val cold = RecurringQueryReader(fixture.provider, fixture.dao,
                LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, fixture.dao))
            assertTrue(cold.items(fixture.binding, null, true, null).isFailure, "$mutationType must retire the old next-due projection")
            assertTrue(cold.occurrence(fixture.binding, "recurring", "current").isFailure)
            assertTrue(cold.occurrence(fixture.binding, "recurring", "2026-09").isFailure)
            api.failure = null
            val verified = cold.occurrence(fixture.binding, "recurring", "current").getOrThrow()
            assertEquals(period, verified.value, "The new period is read from GET, not seeded by a command receipt")
            api.failure = ConnectException("offline after verified period")
            assertEquals(verified.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "current").getOrThrow())
        }
    }

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
            override suspend fun saveRecurringSnapshotIfCurrent(snapshot: StatsProjectionCacheEntity, expectedEpoch: Long, aliasMonth: String?) {
                if (failWrites) throw SQLiteException("projection unavailable")
                saved.saveRecurringSnapshotIfCurrent(snapshot, expectedEpoch, aliasMonth)
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
        reader().history(fixture.binding, "recurring", null).getOrThrow()
        reader().occurrence(fixture.binding, "another-series", "current").getOrThrow()
        reader().occurrence(fixture.binding, "recurring", "current").getOrThrow()
        reader().occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        assertEquals(token, fixture.dao.recurringDirectBarrier(logicalBindingAdapter.toJson(fixture.binding)),
            "Neither history nor any occurrence projection can establish the unknown lifecycle result")
        api.failure = ConnectException("offline after unrelated GETs")
        assertTrue(reader().history(fixture.binding, "recurring", null).isFailure, "Unrelated GETs cannot seed reusable caches across the original barrier")
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

    @Test fun currentAndExplicitMonthKeepLatestReadAtTheSameInstantWhenReopenedOffline() = runTest {
        var offline = false
        var response = RecurringOccurrenceDto("recurring", "2026-09", 9, 0, "unfulfilled", 2400, 2400, null, null, null,
            homeCurrencyCode = "JPY")
        val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
            override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
                if (offline) throw ConnectException("offline period")
                return response
            }
        } })
        val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator, readClock)
        reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        response = response.copy(rowVersion = 1, state = "fulfilled", reservedAmountCents = 0,
            expensePublicId = "paid-original", paidAmountCents = 2400, paidHomeCurrencyCode = "JPY")
        val paid = reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
        offline = true
        val cold = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        assertEquals(paid.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
        offline = false
        reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        response = response.copy(state = "needs_review", paymentReviewReason = "reversed",
            paidAmountCents = null, paidHomeCurrencyCode = null, reservedAmountCents = 2400)
        val reviewed = reader.occurrence(fixture.binding, "recurring", "current").getOrThrow()
        assertEquals("reversed", reviewed.value.paymentReviewReason)
        offline = true
        assertEquals(reviewed.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
        assertEquals(reviewed.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "current").getOrThrow())
        offline = false
        response = response.copy(state = "fulfilled", paymentReviewReason = null,
            paidAmountCents = 2400, paidHomeCurrencyCode = "JPY", reservedAmountCents = 0)
        val resolved = reader.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow()
        assertEquals(null, resolved.value.paymentReviewReason)
        assertEquals(reviewed.fetchedAt, resolved.fetchedAt)
        offline = true
        assertEquals(resolved.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "current").getOrThrow())
        assertEquals(resolved.copy(fromCache = true), cold.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
        assertTrue(cold.occurrence(fixture.binding, "recurring", "2026-08").isFailure)
    }

    @Test fun lateAliasReadCannotReplaceNewerPeriodStateOrInventAnotherMonth() = runTest {
        for (oldPeriod in listOf("2026-09", "current")) for (advanceVersion in listOf(false, true)) {
            val started = CompletableDeferred<Unit>()
            val release = CompletableDeferred<Unit>()
            var offline = false
            val earlier = RecurringOccurrenceDto("recurring", "2026-09", 9, 1, "fulfilled", 2400, 0,
                "paid-original", 2400, null, homeCurrencyCode = "JPY", paidHomeCurrencyCode = "JPY")
            val newer = earlier.copy(seriesRowVersion = if (advanceVersion) 10 else 9, state = "needs_review")
            val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
                override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
                    if (offline) throw ConnectException("offline period")
                    if (month != oldPeriod) return newer
                    started.complete(Unit)
                    release.await()
                    return earlier
                }
            } })
            val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator, readClock)
            val pending = async { reader.occurrence(fixture.binding, "recurring", oldPeriod) }
            started.await()
            val freshPeriod = if (oldPeriod == "current") "2026-09" else "current"
            val fresh = reader.occurrence(fixture.binding, "recurring", freshPeriod).getOrThrow()
            release.complete(Unit)
            pending.await().getOrThrow()
            offline = true
            val reopened = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            assertEquals(fresh.copy(fromCache = true), reopened.occurrence(fixture.binding, "recurring", "2026-09").getOrThrow())
            assertEquals(fresh.copy(fromCache = true), reopened.occurrence(fixture.binding, "recurring", "current").getOrThrow())
            assertTrue(reopened.occurrence(fixture.binding, "recurring", "2026-08").isFailure)
        }
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
