package com.ticketbox.data.repository

import android.app.Application
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.domain.model.RecurringCandidate
import java.net.ConnectException
import java.util.TimeZone
import java.util.UUID
import kotlinx.coroutines.runBlocking
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
class RecurringCandidateRoomTest {
    @Test fun lostReplyReopensOriginalIntentAndReadsCurrentFact() = runBlocking {
        val app = RuntimeEnvironment.getApplication()
        val name = "candidate-${UUID.randomUUID()}.db"
        val previousZone = TimeZone.getDefault()
        fun database() = Room.databaseBuilder(app, AppDatabase::class.java, name).build()
        var db = database()
        try {
            lateinit var probe: RecurringReadProbe
            var receipt: RecurringItemDto? = null
            var dropReply = true
            var effects = 0
            val calls = mutableListOf<Triple<RecurringCandidateConfirmRequestDto, String?, String>>()
            val fixture = GoalReadFixture(decorateDao = { db.expenseDao() }, decorate = { delegate ->
                probe = RecurringReadProbe(delegate)
                object : ApiService by probe {
                    override suspend fun recurringItems(status: String?, includeArchived: Boolean, month: String?, timezone: String?) =
                        RecurringItemListResponseDto(if (receipt == null) emptyList() else listOf(probe.item))
                    override suspend fun confirmRecurringCandidate(request: RecurringCandidateConfirmRequestDto,
                        timezone: String?, idempotencyKey: String): RecurringItemDto {
                        calls += Triple(request, timezone, idempotencyKey)
                        val accepted = receipt ?: probe.item.copy(publicId = "adopted", merchant = request.merchant,
                            merchantKey = request.merchant, rowVersion = 1, source = "candidate", status = "active",
                            homeCurrencyCode = request.homeCurrencyCode, baselineAmountCents = request.amountCents,
                            lastAmountCents = request.amountCents, nextExpectedDate = request.nextExpectedDate).also {
                            receipt = it; probe.item = it; effects++
                        }
                        if (dropReply) { dropReply = false; throw ConnectException("Accepted but reply was lost") }
                        return accepted
                    }
                }
            })
            val adapters = OutboxAdapterGraph()
            fun owner(): Pair<RecurringRepository, OutboxDrainEngine> {
                val outbox = testOutboxRepository(db.pendingMutationDao(), bindingProvider = {
                    fixture.provider.currentSession().toOutboxBinding()
                })
                val reader = RecurringQueryReader(fixture.provider, db.expenseDao(),
                    LocalLedgerSessionCoordinator(boundSettingsStore(), fixture.session.sessionStore, db.expenseDao(), outbox))
                outbox.onRecurringDispatchPreparing = reader::prepareDispatch
                outbox.onRecurringDispatchFinished = reader::finishDispatch
                outbox.onRecurringAccepted = reader::invalidateAccepted
                val repository = RecurringRepository(fixture.provider, outbox, queryReader = reader,
                    candidateAdapter = adapters.recurringCandidateAdapter)
                val guard = LedgerRequestGuard(fixture.provider)
                return repository to OutboxDrainEngine(outbox, listOf(ConfirmRecurringCandidateDispatcher({ row ->
                    guard.bind(expectedLedgerId = row.ledgerId).serviceFor(requireNotNull(row.bindingOrNull()))
                }, adapters.recurringCandidateAdapter)))
            }
            TimeZone.setDefault(TimeZone.getTimeZone("Pacific/Auckland"))
            val (repository, engine) = owner()
            assertTrue(repository.items(fixture.binding, includeArchived = true).getOrThrow().value.isEmpty())
            val candidate = RecurringCandidate("定期订阅", 2400, 3, "2026-09-09T12:00:00Z", "high", "每月观察", "JPY")
            val pending = repository.confirmCandidate(fixture.binding, candidate, "2026-11-09").getOrThrow()
            assertTrue(calls.isEmpty(), "Capturing an adoption never bypasses the durable queue")
            val original = db.pendingMutationDao().allRows().single()
            assertEquals(pending.idempotencyKey, original.idempotencyKey)
            assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.runDrain { engine.drainOnce() })
            assertEquals(1, effects)
            assertEquals("pending", db.pendingMutationDao().allRows().single().status)
            probe.item = requireNotNull(receipt).copy(baselineAmountCents = 3100, status = "paused", rowVersion = 2)
            db.close()
            db = database()
            TimeZone.setDefault(TimeZone.getTimeZone("UTC"))
            val (reopened, replayEngine) = owner()
            val restored = db.pendingMutationDao().allRows().single()
            assertEquals(original.payload, restored.payload)
            assertEquals(original.idempotencyKey, restored.idempotencyKey)
            OutboxDrainWorker.runDrain { replayEngine.drainOnce() }
            assertEquals("done", db.pendingMutationDao().allRows().single().status)
            assertEquals(2, calls.size)
            assertEquals(calls[0], calls[1], "The stored date, timezone, currency and key survive reconstruction")
            assertEquals("Pacific/Auckland", calls[1].second)
            assertEquals(1, effects)
            val current = reopened.items(fixture.binding, includeArchived = true).getOrThrow().value.single()
            assertEquals(3100L, current.baselineAmountCents)
            assertEquals("paused", current.status)
            assertEquals(2L, current.rowVersion)
        } finally {
            db.close()
            app.deleteDatabase(name)
            TimeZone.setDefault(previousZone)
        }
    }
}
