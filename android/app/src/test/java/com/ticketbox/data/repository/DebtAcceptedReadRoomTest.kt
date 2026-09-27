package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.domain.model.DebtListLens
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
    @Test fun restoredResourceRetiresItsFilteredRoomListsWithoutRetiringOtherDebtFacts() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val debt = RepaymentResponseLossProbe().current
            var offline = false
            var missing = false
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { api -> object : ApiService by api {
                override suspend fun debt(publicId: String): DebtDto {
                    if (offline) throw ConnectException("offline after resource recovery")
                    if (missing) throw HttpException(Response.error<Any>(404, """{"error":"debt_not_found"}""".toResponseBody()))
                    return debt.copy(publicId = publicId)
                }
                override suspend fun debts(lens: String?): DebtListResponseDto {
                    if (offline) throw ConnectException("offline after resource recovery")
                    return DebtListResponseDto(listOf(debt, debt.copy(publicId = "other")), debt.homeCurrencyCode)
                }
            } })
            fun reader() = DebtQueryReader(fixture.provider, db.expenseDao(), fixture.coordinator)
            val queries = reader()
            val other = queries.detail(fixture.binding, "other").getOrThrow()
            missing = true
            assertTrue(queries.detail(fixture.binding, debt.publicId).isFailure)
            missing = false
            for (lens in DebtListLens.entries) {
                assertEquals(listOf("other"), queries.list(fixture.binding, lens).getOrThrow().value.debts.map { it.publicId })
            }
            val restored = queries.detail(fixture.binding, debt.publicId).getOrThrow()
            offline = true
            assertEquals(restored.copy(fromCache = true), reader().detail(fixture.binding, debt.publicId).getOrThrow())
            assertEquals(other.copy(fromCache = true), reader().detail(fixture.binding, "other").getOrThrow())
            for (lens in DebtListLens.entries) assertTrue(reader().list(fixture.binding, lens).isFailure)
            offline = false
            val complete = queries.list(fixture.binding, DebtListLens.Ledger).getOrThrow()
            assertEquals(listOf(debt.publicId, "other"), complete.value.debts.map { it.publicId })
            offline = true
            assertEquals(complete.copy(fromCache = true), reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow())
        } finally { db.close() }
    }

    @Test fun originalAcceptedRepaymentAutomaticallyReentersAfterReadCleanupRollbackWithoutRevivingTheOldQuery() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val api = RepaymentResponseLossProbe().apply {
                loseResponse = false
                current = current.copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 50_000)
            }
            var replayFailure: Exception? = null
            val attempts = mutableListOf<OriginalRepaymentCall>()
            val queriedWriteStatuses = java.util.concurrent.CopyOnWriteArrayList<String?>()
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
                        queriedWriteStatuses += db.pendingMutationDao().allRows().singleOrNull()?.status
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
            val originalProtection = requireNotNull(db.expenseDao().debtOutboxReadBarrier(key)).responseJson
            fixture.coordinator.clearLocalCache()
            assertEquals(originalProtection, db.expenseDao().debtOutboxReadBarrier(key)?.responseJson,
                "Settings cache cleanup cannot consume the accepted original's read protection")
            assertTrue(db.expenseDao().statsProjections(key, "debt_detail", "", "d1", "UTC").isEmpty())
            assertTrue(reader().detail(fixture.binding, "d1").isFailure)
            offline = false
            started = CompletableDeferred()
            release = CompletableDeferred()
            val readsBeforeCompletion = queriedWriteStatuses.size
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
            val fresh = late.await().getOrThrow()
            assertEquals(listOf("pending", "done"), queriedWriteStatuses.drop(readsBeforeCompletion),
                "Retiring the old read must issue a real second GET after Done; the original wire cannot cross its epoch")
            started = null
            release = null
            assertFalse(fresh.fromCache)
            assertEquals(40_000L, fresh.value.remainingAmountCents)
            assertEquals("JPY", fresh.value.homeCurrencyCode)
            offline = true
            assertEquals(fresh.copy(fromCache = true), reader().detail(fixture.binding, "d1").getOrThrow())
        } finally { db.close() }
    }
    @Test fun originalRepaymentCredentialRefusalSurvivesCleanupFailureWithoutRevokingAReplacementIdentity() = runBlocking {
        for ((status, rebind) in listOf(401 to false, 403 to false, 401 to true)) {
            val db = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
            try {
                val api = RepaymentResponseLossProbe().apply {
                    loseResponse = false
                    current = current.copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 50_000)
                    refusal = status to "original_request_refused"
                }
                var offline = false
                var beforeRefusal: () -> Unit = {}
                val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = {
                    object : ApiService by api {
                        override suspend fun debt(publicId: String): DebtDto {
                            if (offline) throw ConnectException("offline after the original repayment refusal")
                            return api.current
                        }
                        override suspend fun recordDebtRepayment(publicId: String, request: RepaymentCreateRequestDto,
                            idempotencyKey: String?): DebtRepaymentReceiptDto {
                            beforeRefusal()
                            return api.recordDebtRepayment(publicId, request, idempotencyKey)
                        }
                    }
                })
                val settings = boundSettingsStore()
                fun coordinator() = LocalLedgerSessionCoordinator(settings, fixture.session.sessionStore, db.expenseDao())
                val originalCoordinator = coordinator()
                val reads = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, db.expenseDao(), originalCoordinator))
                val original = reads.getDebt("d1").getOrThrow()
                val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = { fixture.provider.currentSession().toOutboxBinding() })
                outbox.onDebtDispatchPreparing = reads::prepareReadsBeforeDispatch
                outbox.onDebtDispatchFinished = reads::finishReadDispatch
                outbox.onDebtAccepted = reads::invalidateReadsAfterAccepted
                val adapters = OutboxAdapterGraph()
                DebtWriteRepository(fixture.provider, outbox, adapters).saveRepayment(fixture.binding, original.value, 10_000).getOrThrow()
                val queued = db.pendingMutationDao().allRows().single()
                db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_denied_debt_cleanup BEFORE DELETE ON stats_projection_cache " +
                    "WHEN OLD.kind = 'debt_detail' BEGIN SELECT RAISE(ABORT, 'Read cleanup unavailable'); END")
                if (rebind) beforeRefusal = {
                    fixture.session.rebindToDifferentServerForFixture("https://other.example.com", "other-session-token")
                }
                val engine = OutboxDrainEngine(outbox, listOf(RecordDebtRepaymentDispatcher(
                    LedgerRequestGuard(fixture.provider), adapters.debtRepaymentAdapter, adapters.debtRepaymentReceiptAdapter)))
                assertEquals(1, engine.drainOnce().failures)
                val failed = db.pendingMutationDao().allRows().single()
                assertEquals(queued.payload, failed.payload)
                assertEquals(queued.idempotencyKey, failed.idempotencyKey)
                assertEquals(queued.expectedRowVersion, failed.expectedRowVersion)
                assertTrue(api.facts.isEmpty(), "A refused repayment never changes the original balance")
                offline = true
                val cold = DebtRepository(fixture.provider, DebtQueryReader(fixture.provider, db.expenseDao(), coordinator()))
                val reopened = cold.getDebt("d1")
                if (rebind) {
                    assertEquals(null, originalCoordinator.snapshotAccessDenials.value)
                    assertTrue((reopened.exceptionOrNull() as RepositoryException).httpStatusCode != 401)
                } else if (status == 401) {
                    assertEquals(401, (reopened.exceptionOrNull() as RepositoryException).httpStatusCode,
                        "The denied original identity cannot reopen its retained JPY cache after process reconstruction")
                } else {
                    assertEquals(original.copy(fromCache = true), reopened.getOrThrow(), "Write-only refusal retains read permission")
                }
                db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_denied_debt_cleanup")
                if (!rebind) {
                    offline = false
                    val fresh = cold.getDebt("d1").getOrThrow()
                    assertEquals(original.value, fresh.value)
                    offline = true
                    assertEquals(fresh.copy(fromCache = true), cold.getDebt("d1").getOrThrow())
                }
            } finally { db.close() }
        }
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
