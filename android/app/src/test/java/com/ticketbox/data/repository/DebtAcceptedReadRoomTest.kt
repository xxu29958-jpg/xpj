package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.data.remote.dto.DebtRepaymentReceiptDto
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
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class DebtAcceptedReadRoomTest {
    @Test fun originalAcceptedRepaymentAutomaticallyReentersAfterReadCleanupRollbackWithoutRevivingTheOldQuery() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val api = RepaymentResponseLossProbe().apply {
                loseResponse = false
                current = current.copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 50_000)
            }
            var replayFailure: Exception? = null
            val attempts = mutableListOf<OriginalRepaymentCall>()
            var offline = false
            var started: CompletableDeferred<Unit>? = null
            var release: CompletableDeferred<Unit>? = null
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = {
                object : ApiService by api {
                    override suspend fun recordDebtRepayment(publicId: String, request: RepaymentCreateRequestDto,
                        idempotencyKey: String?): DebtRepaymentReceiptDto {
                        attempts += OriginalRepaymentCall(publicId, request, requireNotNull(idempotencyKey))
                        replayFailure?.let { throw it }
                        return api.recordDebtRepayment(publicId, request, idempotencyKey)
                    }
                    override suspend fun debt(publicId: String): DebtDto {
                        if (offline) throw ConnectException("offline after original acceptance")
                        val captured = api.current
                        started?.complete(Unit)
                        release?.await()
                        return captured
                    }
                }
            })
            fun reader() = DebtQueryReader(fixture.provider, db.expenseDao(),
                LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, db.expenseDao()))
            val reads = DebtRepository(fixture.provider, reader())
            val baseline = reads.getDebt("d1").getOrThrow()
            val outbox = testOutboxRepository(db.pendingMutationDao(),
                bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            outbox.onDebtDispatchPreparing = reads::prepareReadsBeforeDispatch
            outbox.onDebtDispatchFinished = reads::finishReadDispatch
            outbox.onDebtAccepted = reads::invalidateReadsAfterAccepted
            val adapters = OutboxAdapterGraph()
            val writes = DebtWriteRepository(fixture.provider, outbox, adapters)
            writes.saveRepayment(fixture.binding, baseline.value, 10_000).getOrThrow()
            val original = db.pendingMutationDao().allRows().single()
            val engine = OutboxDrainEngine(outbox, listOf(RecordDebtRepaymentDispatcher(
                LedgerRequestGuard(fixture.provider), adapters.debtRepaymentAdapter, adapters.debtRepaymentReceiptAdapter)))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_debt_protection BEFORE INSERT ON stats_projection_cache " +
                "WHEN NEW.kind = 'debt_outbox_read_barrier' BEGIN SELECT RAISE(ABORT, 'Debt read protection unavailable'); END")
            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
            assertTrue(attempts.isEmpty(), "A command without durable read protection must remain unsent")
            val notSent = db.pendingMutationDao().allRows().single()
            assertEquals("pending", notSent.status)
            assertEquals(original.retryCount, notSent.retryCount)
            assertEquals(original.payload, notSent.payload)
            assertEquals(original.expectedRowVersion, notSent.expectedRowVersion)
            assertEquals(original.idempotencyKey, notSent.idempotencyKey)
            offline = true
            assertEquals(baseline.copy(fromCache = true), reads.getDebt("d1").getOrThrow())
            offline = false
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_debt_protection")
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_debt_cleanup BEFORE DELETE ON stats_projection_cache " +
                "WHEN OLD.kind = 'debt_detail' BEGIN SELECT RAISE(ABORT, 'Debt read cleanup unavailable'); END")

            started = CompletableDeferred()
            release = CompletableDeferred()
            val beforeAcceptance = async(Dispatchers.IO) { reader().detail(fixture.binding, "d1") }
            requireNotNull(started).await()
            try {
                assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
            } finally { requireNotNull(release).complete(Unit) }
            assertTrue(beforeAcceptance.await().isFailure,
                "An older GET cannot become fresh after a known acceptance whose local publication rolled back")
            started = null
            release = null
            val retry = db.pendingMutationDao().allRows().single()
            assertEquals("pending", retry.status)
            assertEquals("accepted_debt_read_publication_pending", retry.lastError)
            assertEquals(original.retryCount + 1, retry.retryCount, "The accepted delivery retains its actual attempt")
            assertEquals(original.payload, retry.payload)
            assertEquals(original.expectedRowVersion, retry.expectedRowVersion)
            assertEquals(original.idempotencyKey, retry.idempotencyKey)
            assertEquals(1, api.calls.size)
            assertEquals(1, api.facts.size)
            assertEquals(40_000L, api.current.remainingAmountCents)
            val key = logicalBindingAdapter.toJson(fixture.binding)
            assertEquals(null, db.expenseDao().debtReadEpoch(key), "Failed read retirement leaves the original epoch")
            assertEquals(baseline.fetchedAt, db.expenseDao().statsProjections(key, "debt_detail", "", "d1", "UTC").single().fetchedAt)
            offline = true
            assertTrue(reader().detail(fixture.binding, "d1").isFailure, "Rebuilt reader cannot borrow the known accepted command's old query")

            for (failure in listOf(ConnectException("replay offline"), HttpException(Response.error<Any>(503, "unavailable".toResponseBody())))) {
                replayFailure = failure
                assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
                val retried = db.pendingMutationDao().allRows().single()
                assertEquals("pending", retried.status)
                assertTrue(retried.lastError != "accepted_debt_read_publication_pending")
                assertEquals(original.payload, retried.payload)
                assertEquals(original.expectedRowVersion, retried.expectedRowVersion)
                assertEquals(original.idempotencyKey, retried.idempotencyKey)
                assertEquals(1, api.facts.size)
                assertEquals(40_000L, api.current.remainingAmountCents)
                assertTrue(reader().detail(fixture.binding, "d1").isFailure,
                    "A later replay diagnosis cannot release the accepted original's old cached Debt")
            }
            replayFailure = null
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_debt_cleanup")
            offline = false
            started = CompletableDeferred()
            release = CompletableDeferred()
            val late = async(Dispatchers.IO) { reader().detail(fixture.binding, "d1") }
            requireNotNull(started).await()
            try {
                assertEquals(1, engine.drainOnce().done)
                val done = db.pendingMutationDao().allRows().single()
                assertEquals("done", done.status)
                assertEquals(null, done.lastError)
                assertNotNull(done.receiptJson)
                assertEquals(original.payload, done.payload)
                assertEquals(original.expectedRowVersion, done.expectedRowVersion)
                assertEquals(original.idempotencyKey, done.idempotencyKey)
                assertEquals(original.retryCount + 4, done.retryCount)
                assertEquals(api.calls.first(), api.calls.last(), "Automatic retry keeps the original key, body and OCC")
                assertEquals(2, api.calls.size)
                assertEquals(4, attempts.size)
                assertTrue(attempts.all { it == attempts.first() })
                assertEquals(1, api.facts.size, "Same-key reentry does not create another repayment")
                assertEquals("1", db.expenseDao().debtReadEpoch(key))
                assertEquals(null, db.expenseDao().debtOutboxReadBarrier(key))
                assertTrue(db.expenseDao().statsProjections(key, "debt_detail", "", "d1", "UTC").isEmpty())
            } finally { requireNotNull(release).complete(Unit) }
            assertTrue(late.await().isFailure, "Another owner's read begun before Done cannot republish across its epoch")
            offline = true
            assertTrue(reader().detail(fixture.binding, "d1").isFailure, "Receipt is not a replacement GET")
            started = null
            release = null
            offline = false
            val fresh = reader().detail(fixture.binding, "d1").getOrThrow()
            assertFalse(fresh.fromCache)
            assertEquals(40_000L, fresh.value.remainingAmountCents)
            assertEquals("JPY", fresh.value.homeCurrencyCode)
            offline = true
            assertEquals(fresh.copy(fromCache = true), reader().detail(fixture.binding, "d1").getOrThrow())
        } finally { db.close() }
    }
    @Test fun unsentAndDefiniteRefusalsPreserveReadFactsWhileAnEarlierUnknownAcceptanceSurvivesDropAndCleanup() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val api = RepaymentResponseLossProbe().apply { loseResponse = false }
            var offline = false
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = {
                object : ApiService by api {
                    override suspend fun debt(publicId: String): DebtDto {
                        if (offline) throw ConnectException("offline original Debt read")
                        return api.current
                    }
                }
            })
            fun reader() = DebtQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            val queryReader = reader()
            val reads = DebtRepository(fixture.provider, queryReader)
            val baseline = reads.getDebt("d1").getOrThrow()
            val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
            outbox.onDebtDispatchPreparing = reads::prepareReadsBeforeDispatch
            outbox.onDebtDispatchFinished = reads::finishReadDispatch
            outbox.onDebtAccepted = reads::invalidateReadsAfterAccepted
            val adapters = OutboxAdapterGraph()
            val writes = DebtWriteRepository(fixture.provider, outbox, adapters)
            val engine = OutboxDrainEngine(outbox, listOf(RecordDebtRepaymentDispatcher(
                LedgerRequestGuard(fixture.provider), adapters.debtRepaymentAdapter, adapters.debtRepaymentReceiptAdapter)))
            val key = logicalBindingAdapter.toJson(fixture.binding)
            val invalid = outbox.enqueue(PendingMutationType.RecordDebtRepayment, "debt:d1", "{}", 1, idempotencyKey = "invalid-original")
            assertEquals(1, engine.drainOnce().failures)
            assertTrue(api.calls.isEmpty(), "An unsupported frozen original is refused before dispatch")
            assertEquals(null, db.expenseDao().debtOutboxReadBarrier(key))
            offline = true
            assertEquals(baseline.copy(fromCache = true), reads.getDebt("d1").getOrThrow())
            assertTrue(outbox.resolveFailed(invalid, FailedResolution.Drop))
            writes.saveRepayment(fixture.binding, baseline.value, 10_000).getOrThrow()
            api.refusal = 403 to "forbidden"
            assertEquals(1, engine.drainOnce().failures)
            assertTrue(api.facts.isEmpty())
            assertEquals(null, db.expenseDao().debtOutboxReadBarrier(key))
            assertEquals(baseline.copy(fromCache = true), reader().detail(fixture.binding, "d1").getOrThrow(),
                "A write-only refusal leaves previously authorized read facts available")
            assertTrue(outbox.resolveFailed(db.pendingMutationDao().allRows().single().id, FailedResolution.Drop))
            writes.saveRepayment(fixture.binding, baseline.value, 10_000).getOrThrow()
            val original = db.pendingMutationDao().allRows().single()
            api.refusal = null
            api.loseResponse = true
            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
            assertEquals(1, api.facts.size)
            val unknownToken = requireNotNull(db.expenseDao().debtOutboxReadBarrier(key)).responseJson
            api.refusal = 403 to "forbidden"
            assertEquals(1, engine.drainOnce().failures)
            val failed = db.pendingMutationDao().allRows().single()
            assertEquals(original.payload, failed.payload)
            assertEquals(original.expectedRowVersion, failed.expectedRowVersion)
            assertEquals(original.idempotencyKey, failed.idempotencyKey)
            val retainedToken = requireNotNull(db.expenseDao().debtOutboxReadBarrier(key)).responseJson
            assertTrue(unknownToken != retainedToken, "Every original-key dispatch carries a distinct read proof")
            assertTrue(outbox.resolveFailed(failed.id, FailedResolution.Drop))
            assertEquals(0, outbox.clearAll())
            assertEquals(retainedToken, db.expenseDao().debtOutboxReadBarrier(key)?.responseJson)
            assertTrue(reader().detail(fixture.binding, "d1").isFailure,
                "Dropping an unknown original cannot resurrect its accepted-before-read cache")
            offline = false
            api.refusal = null
            val fresh = reader().detail(fixture.binding, "d1").getOrThrow()
            assertEquals(40_000L, fresh.value.remainingAmountCents)
            assertEquals(null, db.expenseDao().debtOutboxReadBarrier(key))
            offline = true
            assertEquals(fresh.copy(fromCache = true), reader().detail(fixture.binding, "d1").getOrThrow())
            assertEquals(1, api.facts.size)
        } finally { db.close() }
    }

}
