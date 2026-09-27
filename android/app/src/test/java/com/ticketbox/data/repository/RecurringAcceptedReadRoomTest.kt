package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
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
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                api = RecurringReadProbe(delegate)
                object : ApiService by api {
                    override suspend fun updateRecurringItem(publicId: String, request: RecurringItemUpdateRequestDto, idempotencyKey: String) =
                        api.item.copy(merchant = requireNotNull(request.merchant), rowVersion = request.expectedRowVersion + 1)
                            .also { calls += idempotencyKey to request }
                }
            })
            val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            val reader = RecurringQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            outbox.onRecurringAccepted = reader::invalidateAccepted
            val adapters = OutboxAdapterGraph()
            val repository = RecurringRepository(fixture.provider, outbox, adapters.recurringCreateAdapter,
                adapters.recurringUpdateAdapter, queryReader = reader)
            val baseline = repository.items(fixture.binding, includeArchived = true).getOrThrow().value.single()
            repository.updateAllowingOffline(fixture.binding, baseline, RecurringItemPatch(merchant = "已接受的原修改", homeCurrencyCode = "JPY")).getOrThrow()
            val original = db.pendingMutationDao().allRows().single()
            val guard = LedgerRequestGuard(fixture.provider)
            val engine = OutboxDrainEngine(outbox, listOf(UpdateRecurringItemDispatcher({ row ->
                guard.bind(expectedLedgerId = row.ledgerId).serviceFor(requireNotNull(row.bindingOrNull()))
            }, adapters.recurringUpdateAdapter)))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_recurring_cleanup BEFORE DELETE ON stats_projection_cache " +
                "WHEN OLD.kind = 'recurring_items' BEGIN SELECT RAISE(ABORT, 'Read cleanup unavailable'); END")
            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
            val retry = db.pendingMutationDao().allRows().single()
            assertEquals("pending", retry.status, "Local publication failure must automatically release the original claim for worker retry")
            assertEquals(original.retryCount + 1, retry.retryCount, "A real accepted send is not refunded")
            assertEquals(original.payload, retry.payload)
            assertEquals(original.expectedRowVersion, retry.expectedRowVersion)
            assertEquals(original.idempotencyKey, retry.idempotencyKey)
            assertEquals(listOf(original.idempotencyKey), calls.map { it.first })
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
                val done = db.pendingMutationDao().allRows().single()
                assertEquals(original.payload, done.payload)
                assertEquals(original.expectedRowVersion, done.expectedRowVersion)
                assertEquals(original.idempotencyKey, done.idempotencyKey)
                assertEquals("done", done.status)
                assertEquals(original.retryCount + 2, done.retryCount)
                val bindingKey = logicalBindingAdapter.toJson(fixture.binding)
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
}
