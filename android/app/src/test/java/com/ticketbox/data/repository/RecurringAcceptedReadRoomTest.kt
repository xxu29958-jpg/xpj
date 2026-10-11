package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringItemTokenRequest
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import java.net.ConnectException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class RecurringAcceptedReadRoomTest {
    @Test fun lateReadRefusalDuringDirectPausePreservesItsBarrierAndTrueAcceptance() = runBlocking {
        for (status in listOf(401, 403)) {
            val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
            try {
                lateinit var api: RecurringReadProbe
                val readStarted = CompletableDeferred<Unit>()
                val readRelease = CompletableDeferred<Unit>()
                val sendStarted = CompletableDeferred<Unit>()
                val sendRelease = CompletableDeferred<Unit>()
                var refusingRead = false
                val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                    api = RecurringReadProbe(delegate)
                    object : ApiService by api {
                        override suspend fun recurringItems(state: String?, includeArchived: Boolean, month: String?, timezone: String?) =
                            if (!refusingRead) api.recurringItems(state, includeArchived, month, timezone) else {
                                readStarted.complete(Unit)
                                readRelease.await()
                                throw HttpException(Response.error<Any>(status, "".toResponseBody()))
                            }
                        override suspend fun pauseRecurringItem(publicId: String, request: RecurringItemTokenRequest) =
                            api.item.copy(status = "paused", rowVersion = 10).also {
                                sendStarted.complete(Unit)
                                sendRelease.await()
                            }
                    }
                })
                val reader = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
                val repository = RecurringRepository(fixture.provider, queryReader = reader)
                reader.items(fixture.binding, null, true, null).getOrThrow()
                refusingRead = true
                val late = async(Dispatchers.IO) { reader.items(fixture.binding, null, true, null) }
                readStarted.await()
                val dispatch = async(Dispatchers.IO) { repository.pause(fixture.binding, "recurring", 9) }
                sendStarted.await()
                val bindingKey = logicalBindingAdapter.toJson(fixture.binding)
                val token = requireNotNull(db.expenseDao().recurringDirectBarrier(bindingKey))
                readRelease.complete(Unit)
                assertTrue(late.await().isFailure)
                assertEquals(token, db.expenseDao().recurringDirectBarrier(bindingKey),
                    "Shared refusal deletes read payloads, not an executing mutation's persistent proof")
                sendRelease.complete(Unit)
                assertEquals("paused", dispatch.await().getOrThrow().status, "A read refusal cannot turn a real mutation ACK into failure")
                refusingRead = false
                api.failure = ConnectException("cold offline after ACK")
                val cold = RecurringQueryReader(fixture.provider, db.expenseDao(),
                    LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, db.expenseDao()))
                assertTrue(cold.items(fixture.binding, null, true, null).isFailure)
                assertEquals("1", db.expenseDao().recurringReadEpoch(bindingKey))
            } finally { db.close() }
        }
    }

    @Test fun acceptedDirectPauseWithFailedCleanupCannotResurrectOldSnapshotsInRebuiltOwner() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            lateinit var api: RecurringReadProbe
            var calls = 0
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun pauseRecurringItem(publicId: String, request: RecurringItemTokenRequest) =
                        api.item.copy(status = "paused", rowVersion = 10).also { calls++ }
                }
            })
            fun reader() = RecurringQueryReader(fixture.provider, db.expenseDao(),
                LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, db.expenseDao()))
            val old = reader()
            old.items(fixture.binding, null, true, null).getOrThrow()
            old.history(fixture.binding, "recurring", null).getOrThrow()
            old.occurrence(fixture.binding, "recurring", "current").getOrThrow()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_direct_cleanup BEFORE DELETE ON stats_projection_cache " +
                "WHEN OLD.kind = 'recurring_items' BEGIN SELECT RAISE(ABORT, 'Read cleanup unavailable'); END")
            val repository = RecurringRepository(fixture.provider, queryReader = old)
            assertEquals("paused", repository.pause(fixture.binding, "recurring", 9).getOrThrow().status)
            val bindingKey = logicalBindingAdapter.toJson(fixture.binding)
            assertTrue(db.expenseDao().recurringDirectBarrier(bindingKey) != null, "Cleanup rollback preserves the dispatch token")
            api.failure = ConnectException("offline after acceptance")
            assertTrue(reader().items(fixture.binding, null, true, null).isFailure)
            assertTrue(reader().history(fixture.binding, "recurring", null).isFailure)
            assertTrue(reader().occurrence(fixture.binding, "recurring", "current").isFailure)
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_direct_cleanup")
            api.failure = null
            api.item = api.item.copy(status = "paused", rowVersion = 10)
            val current = reader().items(fixture.binding, null, true, null).getOrThrow()
            api.failure = ConnectException("offline after verified GET")
            assertEquals(current.copy(fromCache = true), reader().items(fixture.binding, null, true, null).getOrThrow())
            assertEquals(null, db.expenseDao().recurringDirectBarrier(bindingKey))
            assertTrue(reader().history(fixture.binding, "recurring", null).isFailure, "Only the actual GET was republished")
            assertEquals(1, calls)
        } finally { db.close() }
    }

    @Test fun failedDurableBarrierDoesNotDispatchOrEraseAlreadyReadList() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            lateinit var api: RecurringReadProbe
            var calls = 0
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun pauseRecurringItem(publicId: String, request: RecurringItemTokenRequest) =
                        api.item.copy(status = "paused", rowVersion = 10).also { calls++ }
                }
            })
            val reader = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            val original = reader.items(fixture.binding, null, true, null).getOrThrow()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_direct_barrier BEFORE INSERT ON stats_projection_cache " +
                "WHEN NEW.kind = 'recurring_direct_barrier' BEGIN SELECT RAISE(ABORT, 'Barrier unavailable'); END")
            val unsent = RecurringRepository(fixture.provider, queryReader = reader).pause(fixture.binding, "recurring", 9)
            assertTrue(unsent.isFailure)
            assertTrue(unsent.exceptionOrNull()?.message.orEmpty().contains("尚未发送"))
            assertEquals(0, calls)
            api.failure = ConnectException("offline after unsent request")
            assertEquals(original.copy(fromCache = true), reader.items(fixture.binding, null, true, null).getOrThrow())
        } finally { db.close() }
    }

    @Test fun acceptedOriginalCannotSettleDoneWithOldReadCacheAndReentryKeepsItsKeyBodyAndOcc() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            lateinit var api: RecurringReadProbe
            val calls = mutableListOf<Pair<String, RecurringItemUpdateRequestDto>>()
            var replayFailure: Exception? = null
            var businessEffects = 0
            var acceptedResult: com.ticketbox.data.remote.dto.RecurringItemDto? = null
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun updateRecurringItem(publicId: String, request: RecurringItemUpdateRequestDto, idempotencyKey: String): com.ticketbox.data.remote.dto.RecurringItemDto {
                        calls += idempotencyKey to request
                        replayFailure?.let { throw it }
                        return acceptedResult ?: api.item.copy(merchant = requireNotNull(request.merchant), rowVersion = request.expectedRowVersion + 1)
                            .also { acceptedResult = it; businessEffects++ }
                    }
                }
            })
            val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            val reader = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            outbox.onRecurringDispatchPreparing = reader::prepareDispatch
            outbox.onRecurringDispatchFinished = reader::finishDispatch
            outbox.onRecurringAccepted = reader::invalidateAccepted
            val adapters = OutboxAdapterGraph()
            val repository = RecurringRepository(fixture.provider, outbox, adapters, queryReader = reader)
            val baseline = repository.items(fixture.binding, includeArchived = true).getOrThrow().value.single()
            repository.updateAllowingOffline(fixture.binding, baseline, RecurringItemPatch(merchant = "已接受的原修改", homeCurrencyCode = "JPY")).getOrThrow()
            val original = db.pendingMutationDao().allRows().single()
            val guard = LedgerRequestGuard(fixture.provider)
            val engine = OutboxDrainEngine(outbox, listOf(UpdateRecurringItemDispatcher({ row ->
                guard.bind(expectedLedgerId = row.ledgerId).serviceFor(requireNotNull(row.bindingOrNull()))
            }, adapters.recurringUpdateAdapter)))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_recurring_protection BEFORE INSERT ON stats_projection_cache " +
                "WHEN NEW.kind = 'recurring_outbox_read_barrier' BEGIN SELECT RAISE(ABORT, 'Read protection unavailable'); END")
            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
            assertTrue(calls.isEmpty(), "Without durable read protection the original command must not be sent")
            val notSent = db.pendingMutationDao().allRows().single()
            assertEquals("pending", notSent.status)
            assertEquals(original.retryCount, notSent.retryCount, "An unsent attempt is refunded for automatic retry")
            assertEquals(original.payload, notSent.payload)
            assertEquals(original.expectedRowVersion, notSent.expectedRowVersion)
            assertEquals(original.idempotencyKey, notSent.idempotencyKey)
            api.failure = ConnectException("offline after protection could not be stored")
            assertEquals(baseline, reader.items(fixture.binding, null, true, null).getOrThrow().value.single(),
                "A command which could not be sent preserves the already-read facts")
            api.failure = null
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_recurring_protection")
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_recurring_cleanup BEFORE DELETE ON stats_projection_cache " +
                "WHEN OLD.kind = 'recurring_items' BEGIN SELECT RAISE(ABORT, 'Read cleanup unavailable'); END")
            val bindingKey = logicalBindingAdapter.toJson(fixture.binding)
            val oldCache = db.expenseDao().statsProjections(bindingKey, "recurring_items", "", ":true", java.util.TimeZone.getDefault().id)
            assertEquals(1, oldCache.size)
            api.started = CompletableDeferred()
            api.release = CompletableDeferred()
            val beforeAcceptance = async(Dispatchers.IO) {
                RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator).items(fixture.binding, null, true, null)
            }
            requireNotNull(api.started).await()
            api.started = CompletableDeferred()
            val freshBeforeAcceptance = async(Dispatchers.IO) {
                RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
                    .freshQuery(fixture.binding, { recurringItems(null, true, null, java.util.TimeZone.getDefault().id) }, {})
            }
            requireNotNull(api.started).await()
            try {
                assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
                val retry = db.pendingMutationDao().allRows().single()
                assertEquals("pending", retry.status, "Local publication failure must automatically release the original claim for worker retry")
                assertEquals(original.retryCount + 1, retry.retryCount, "A real accepted send is not refunded")
                assertEquals(original.payload, retry.payload)
                assertEquals(original.expectedRowVersion, retry.expectedRowVersion)
                assertEquals(original.idempotencyKey, retry.idempotencyKey)
                assertEquals(listOf(original.idempotencyKey), calls.map { it.first })
                assertEquals("accepted_recurring_read_publication_pending", retry.lastError)
            } finally { requireNotNull(api.release).complete(Unit) }
            assertTrue(beforeAcceptance.await().isFailure, "Another owner's GET begun before known acceptance cannot publish after failed settlement")
            assertTrue(freshBeforeAcceptance.await().isFailure, "Fresh-only reminder reads obey the same accepted-pending race barrier")
            api.started = null
            api.release = null
            api.failure = ConnectException("cold offline while accepted cleanup is still Pending")
            val cold = RecurringQueryReader(fixture.provider, db.expenseDao(),
                LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, db.expenseDao()))
            assertTrue(cold.items(fixture.binding, null, true, null).isFailure,
                "An accepted original waiting for Room publication cannot resurrect its pre-acceptance cache")
            for (failure in listOf(ConnectException("replay offline"), HttpException(Response.error<Any>(503, "unavailable".toResponseBody())))) {
                replayFailure = failure
                assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
                val retried = db.pendingMutationDao().allRows().single()
                assertEquals("pending", retried.status)
                assertTrue(retried.lastError != "accepted_recurring_read_publication_pending", "The current replay diagnosis may change without releasing read retirement")
                assertEquals(original.payload, retried.payload)
                assertEquals(original.expectedRowVersion, retried.expectedRowVersion)
                assertEquals(original.idempotencyKey, retried.idempotencyKey)
                assertTrue(RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
                    .items(fixture.binding, null, true, null).isFailure, "A later replay failure cannot resurrect a known accepted original's old cache")
            }
            replayFailure = null
            val protection = requireNotNull(db.expenseDao().recurringOutboxReadBarrier(bindingKey))
            assertTrue(protection.responseJson.startsWith(requireNotNull(original.idempotencyKey)))
            assertEquals(1, businessEffects)
            api.failure = null
            api.item = api.item.copy(merchant = "已接受的原修改", rowVersion = 10)
            val pendingFresh = cold.items(fixture.binding, null, true, null).getOrThrow()
            assertEquals("已接受的原修改", pendingFresh.value.single().merchant)
            assertTrue(!pendingFresh.fromCache)
            assertEquals(oldCache, db.expenseDao().statsProjections(bindingKey, "recurring_items", "", ":true", java.util.TimeZone.getDefault().id),
                "A GET started with known accepted-pending state may display its actual result but cannot publish a cache")
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_recurring_cleanup")
            api.started = CompletableDeferred()
            api.release = CompletableDeferred()
            val late = async(Dispatchers.IO) {
                RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator).items(fixture.binding, null, true, null)
            }
            requireNotNull(api.started).await()
            try {
                assertEquals(1, engine.drainOnce().done)
                assertEquals(calls.first(), calls.last())
                assertEquals(1, businessEffects, "Original-key replay applies the business change once")
                val done = db.pendingMutationDao().allRows().single()
                assertEquals(original.payload, done.payload)
                assertEquals(original.expectedRowVersion, done.expectedRowVersion)
                assertEquals(original.idempotencyKey, done.idempotencyKey)
                assertEquals("done", done.status)
                assertEquals(original.retryCount + 4, done.retryCount)
                assertEquals("1", db.expenseDao().recurringReadEpoch(bindingKey))
                assertEquals(1, db.pendingMutationDao().deleteResolvedBefore("done", "2099-01-01T00:00:00Z"))
                assertEquals("1", db.expenseDao().recurringReadEpoch(bindingKey), "Ordinary Done cleanup cannot reset the query epoch")
            } finally { requireNotNull(api.release).complete(Unit) }
            assertTrue(late.await().isFailure, "A different query owner cannot republish a read begun before acceptance")
            api.failure = ConnectException("offline after original acceptance")
            assertTrue(RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
                .items(fixture.binding, null, true, null).isFailure, "An accepted command's receipt is not a current list query")
        } finally { db.close() }
    }
    @Test fun definiteRefusalKeepsReadFactsButCannotEraseAnEarlierUnknownAttemptOrItsDroppedOriginal() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            lateinit var api: RecurringReadProbe
            var updateCalls = 0
            var sendStarted: CompletableDeferred<Unit>? = null
            var sendRelease: CompletableDeferred<Unit>? = null
            var failure: Exception = HttpException(Response.error<Any>(409,
                """{"error":"state_conflict","message":"原版本已变化"}""".toResponseBody()))
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun updateRecurringItem(publicId: String, request: RecurringItemUpdateRequestDto, idempotencyKey: String):
                        com.ticketbox.data.remote.dto.RecurringItemDto {
                        updateCalls++
                        sendStarted?.complete(Unit)
                        sendRelease?.await()
                        throw failure
                    }
                    override suspend fun pauseRecurringItem(publicId: String, request: RecurringItemTokenRequest) =
                        api.item.copy(status = "paused", rowVersion = 10)
                }
            })
            val reader = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            val original = reader.items(fixture.binding, null, true, null).getOrThrow()
            val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            outbox.onRecurringDispatchPreparing = reader::prepareDispatch
            outbox.onRecurringDispatchFinished = reader::finishDispatch
            outbox.onRecurringAccepted = reader::invalidateAccepted
            val adapters = OutboxAdapterGraph()
            val repository = RecurringRepository(fixture.provider, outbox, adapters, queryReader = reader)
            val guard = LedgerRequestGuard(fixture.provider)
            val engine = OutboxDrainEngine(outbox, listOf(UpdateRecurringItemDispatcher({ row ->
                guard.bind(expectedLedgerId = row.ledgerId).serviceFor(requireNotNull(row.bindingOrNull()))
            }, adapters.recurringUpdateAdapter)))
            val invalidId = outbox.enqueue(PendingMutationType.UpdateRecurringItem, "recurring_item:recurring", "{}", 9, idempotencyKey = "invalid-original")
            assertEquals(1, engine.drainOnce().failures)
            assertEquals(0, updateCalls, "An unsupported original is rejected before any HTTP dispatch")
            api.failure = ConnectException("offline after an unsent refusal")
            assertEquals(original.copy(fromCache = true), reader.items(fixture.binding, null, true, null).getOrThrow())
            assertTrue(outbox.resolveFailed(invalidId, FailedResolution.Drop))
            repository.updateAllowingOffline(fixture.binding, original.value.single(), RecurringItemPatch(merchant = "保留的编辑",
                homeCurrencyCode = requireNotNull(original.value.single().homeCurrencyCode))).getOrThrow()
            assertEquals(1, engine.drainOnce().conflicts)
            val bindingKey = logicalBindingAdapter.toJson(fixture.binding)
            assertEquals(null, db.expenseDao().recurringOutboxReadBarrier(bindingKey))
            api.failure = ConnectException("offline after a definite refusal")
            assertEquals(original.copy(fromCache = true), reader.items(fixture.binding, null, true, null).getOrThrow())
            assertTrue(outbox.resolveConflict(db.pendingMutationDao().allRows().single().id, ConflictResolution.DropMine))
            repository.updateAllowingOffline(fixture.binding, original.value.single(), RecurringItemPatch(merchant = "未知原提交",
                homeCurrencyCode = requireNotNull(original.value.single().homeCurrencyCode))).getOrThrow()
            failure = ConnectException("unknown dispatch result")
            sendStarted = CompletableDeferred()
            sendRelease = CompletableDeferred()
            val inFlight = async(Dispatchers.IO) { OutboxDrainWorker.runDrain { engine.drainOnce() } }
            requireNotNull(sendStarted).await()
            val executingToken = requireNotNull(db.expenseDao().recurringOutboxReadBarrier(bindingKey)).responseJson
            try {
                assertEquals("paused", repository.pause(fixture.binding, "recurring", 9).getOrThrow().status)
                assertEquals(executingToken, db.expenseDao().recurringOutboxReadBarrier(bindingKey)?.responseJson,
                    "A parallel direct ACK must not consume an executing Outbox attempt's read protection")
            } finally { requireNotNull(sendRelease).complete(Unit) }
            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, inFlight.await())
            sendStarted = null
            sendRelease = null
            val unknown = requireNotNull(db.expenseDao().recurringOutboxReadBarrier(bindingKey)).responseJson
            failure = HttpException(Response.error<Any>(409, """{"error":"state_conflict","message":"原版本已变化"}""".toResponseBody()))
            assertEquals(1, engine.drainOnce().conflicts)
            val retryToken = requireNotNull(db.expenseDao().recurringOutboxReadBarrier(bindingKey)).responseJson
            assertTrue(unknown != retryToken, "Every dispatch has a unique read proof even when its business key is preserved")
            assertTrue(outbox.resolveConflict(db.pendingMutationDao().allRows().single().id, ConflictResolution.DropMine))
            assertEquals(0, outbox.clearAll())
            assertEquals(retryToken, db.expenseDao().recurringOutboxReadBarrier(bindingKey)?.responseJson,
                "Dropping or clearing Outbox originals cannot release an unresolved read projection")
            val cold = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            assertTrue(cold.items(fixture.binding, null, true, null).isFailure)
            api.failure = null
            api.item = api.item.copy(merchant = "实际当前定义", rowVersion = 10)
            assertEquals("实际当前定义", cold.items(fixture.binding, null, true, null).getOrThrow().value.single().merchant)
            assertEquals(null, db.expenseDao().recurringOutboxReadBarrier(bindingKey))
            api.failure = ConnectException("offline after verified current list")
            assertEquals("实际当前定义", cold.items(fixture.binding, null, true, null).getOrThrow().value.single().merchant)
        } finally { db.close() }
    }

    @Test fun clearingLocalCacheDuringPausePreservesTheRealAcknowledgementAndRequiresAnActualNewRead() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            lateinit var api: RecurringReadProbe
            val started = CompletableDeferred<Unit>()
            val release = CompletableDeferred<Unit>()
            var commands = 0
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun pauseRecurringItem(publicId: String, request: RecurringItemTokenRequest):
                        com.ticketbox.data.remote.dto.RecurringItemDto {
                        commands++
                        started.complete(Unit)
                        release.await()
                        api.item = api.item.copy(status = "paused", rowVersion = 10)
                        return api.item
                    }
                }
            })
            val reader = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            val baseline = reader.items(fixture.binding, null, true, null).getOrThrow()
            val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            val adapters = OutboxAdapterGraph()
            val repository = RecurringRepository(fixture.provider, outbox, adapters, queryReader = reader)
            val pending = async(Dispatchers.IO) { repository.pause(fixture.binding, baseline.value.single().publicId, baseline.value.single().rowVersion) }
            started.await()
            val key = logicalBindingAdapter.toJson(fixture.binding)
            val token = requireNotNull(db.expenseDao().recurringDirectBarrier(key)).responseJson
            val reopened = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            try {
                fixture.coordinator.clearLocalCache()
                assertEquals(token, db.expenseDao().recurringDirectBarrier(key)?.responseJson)
                assertTrue(db.expenseDao().statsProjections(key, "recurring_items", "", ":true", java.util.TimeZone.getDefault().id).isEmpty())
                assertTrue(reopened.items(fixture.binding, null, true, null).isFailure,
                    "Clearing cache cannot permit an in-flight command's pre-acceptance query to refill it")
            } finally { release.complete(Unit) }
            assertEquals("paused", pending.await().getOrThrow().status, "Cache cleanup cannot turn the actual ACK into failure")
            assertEquals(1, commands)
            api.failure = ConnectException("offline after accepted pause")
            assertTrue(reopened.items(fixture.binding, null, true, null).isFailure, "The ACK is not a cached query")
            api.failure = null
            val fresh = reopened.items(fixture.binding, null, true, null).getOrThrow()
            assertEquals("paused", fresh.value.single().status)
            assertEquals(baseline.value.single().homeCurrencyCode, fresh.value.single().homeCurrencyCode)
            api.failure = ConnectException("offline after reading current pause")
            assertEquals(fresh.copy(fromCache = true), reopened.items(fixture.binding, null, true, null).getOrThrow())
        } finally { db.close() }
    }

}
