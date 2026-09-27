package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import java.net.ConnectException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
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
            var offline = false
            var started: CompletableDeferred<Unit>? = null
            var release: CompletableDeferred<Unit>? = null
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = {
                object : ApiService by api {
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
            outbox.onDebtAccepted = reads::invalidateReadsAfterAccepted
            val adapters = OutboxAdapterGraph()
            val writes = DebtWriteRepository(fixture.provider, outbox, adapters)
            writes.saveRepayment(fixture.binding, baseline.value, 10_000).getOrThrow()
            val original = db.pendingMutationDao().allRows().single()
            val engine = OutboxDrainEngine(outbox, listOf(RecordDebtRepaymentDispatcher(
                LedgerRequestGuard(fixture.provider), adapters.debtRepaymentAdapter, adapters.debtRepaymentReceiptAdapter)))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_debt_cleanup BEFORE DELETE ON stats_projection_cache " +
                "WHEN OLD.kind = 'debt_detail' BEGIN SELECT RAISE(ABORT, 'Debt read cleanup unavailable'); END")

            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
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
            assertEquals(null, db.expenseDao().debtReadEpoch(key), "Failed Done publication rolls back its epoch")
            assertEquals(baseline.fetchedAt, db.expenseDao().statsProjections(key, "debt_detail", "", "d1", "UTC").single().fetchedAt)
            offline = true
            assertTrue(reader().detail(fixture.binding, "d1").isFailure, "Rebuilt reader cannot borrow the known accepted command's old query")

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
                assertEquals(original.retryCount + 2, done.retryCount)
                assertEquals(api.calls.first(), api.calls.last(), "Automatic retry keeps the original key, body and OCC")
                assertEquals(2, api.calls.size)
                assertEquals(1, api.facts.size, "Same-key reentry does not create another repayment")
                assertEquals("1", db.expenseDao().debtReadEpoch(key))
                assertFalse(db.expenseDao().hasUnpublishedAcceptedDebt(fixture.binding.ownerKey, fixture.binding.ledgerId))
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
}
