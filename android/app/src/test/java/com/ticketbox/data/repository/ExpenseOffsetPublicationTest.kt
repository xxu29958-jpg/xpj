package com.ticketbox.data.repository

import android.app.Application
import com.ticketbox.AppContainer
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.notification.budget.CheckerHarness
import com.ticketbox.notification.budget.budgetOf
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/** The real AppContainer publisher, native Room, dispatcher, drain and budget checker share this journey. */
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class ExpenseOffsetPublicationTest {
    @Test
    fun acceptedOffsetsNotifyAfterCacheAndKeepNotificationFailureOutOfTheOriginalReceipt() = runBlocking(Dispatchers.IO) {
        val context: Application = RuntimeEnvironment.getApplication()
        val container = AppContainer(context)
        val database = AppDatabase.getDatabase(context)
        val fixture = OffsetPublicationFixture(container, database)
        try {
            fixture.acceptedCreateAndVoidReachTheRealBudgetChecker()
            fixture.notificationFailureCannotRetryAnAcceptedVoid()
            fixture.olderBundleCannotNotifyForARejectedCacheVersion()
            fixture.oldBindingCannotDispatchOrNotify()
            fixture.cacheFailureCannotPublishANotification()
        } finally {
            database.close()
        }
    }
}

private class OffsetPublicationFixture(
    private val container: AppContainer,
    private val database: AppDatabase,
) {
    private val adapters = OutboxAdapterGraph()
    private val dao = database.expenseDao()
    private var version = 7L
    private var request: Pair<Any, String>? = null
    private val publishCreate = registeredPublisher(PendingMutationType.CreateExpenseOffset)
    private val publishVoid = registeredPublisher(PendingMutationType.VoidExpenseOffset)

    suspend fun acceptedCreateAndVoidReachTheRealBudgetChecker() {
        for (type in listOf(PendingMutationType.CreateExpenseOffset, PendingMutationType.VoidExpenseOffset)) {
            val response = bundle(++version, voided = type == PendingMutationType.VoidExpenseOffset)
            val budget = CheckerHarness(budgetResult = {
                Result.success(budgetOf(month = "2026-09", overspentCents = 200L))
            }).apply { activeLedgerId = "owner"; month = "2026-09" }
            container.expenseRepository.onConfirmedCommitted = { ledgerId ->
                runBlocking {
                    assertEquals(response.root.rowVersion, dao.findByServerId(ledgerId, 9)?.rowVersion)
                    assertEquals(response.activeOffsets.size, dao.getConfirmedStreamOffsets(ledgerId).size)
                }
                budget.checker.checkAfterConfirmedWrite(ledgerId)
            }
            val replay = replay(type, response)
            assertEquals(1, replay.engine.drainOnce().done)
            assertEquals(1L, replay.outbox.acceptedReplayRevision.value, "UI refresh is a separate accepted-result consumer")
            assertEquals(1, budget.sourceCalls, "The registered offset publisher must trigger the fresh budget query")
            assertEquals("v1:budget:owner:2026-09", budget.dispatched.single().key)
            assertEquals(200L, budget.dispatched.single().overspentCents)
            assertOriginalDone(replay)
            assertEquals(0, replay.engine.drainOnce().attempted)
            assertEquals(1, budget.sourceCalls)
        }
    }

    suspend fun notificationFailureCannotRetryAnAcceptedVoid() {
        var attempts = 0
        container.expenseRepository.onConfirmedCommitted = { attempts++; throw IOException("notification unavailable") }
        val replay = replay(PendingMutationType.VoidExpenseOffset, bundle(++version, voided = true))
        assertEquals(1, replay.engine.drainOnce().done)
        assertEquals(1, attempts)
        assertOriginalDone(replay)
        assertEquals(1L, replay.outbox.acceptedReplayRevision.value)
        assertEquals(0, replay.engine.drainOnce().attempted)
    }

    suspend fun olderBundleCannotNotifyForARejectedCacheVersion() {
        val latest = bundle(version + 2, voided = true).toCacheProjection("owner")
        dao.applyExpenseFactBundle("owner", latest.root, latest.activeOffsets)
        var attempts = 0
        container.expenseRepository.onConfirmedCommitted = { attempts++ }
        val replay = replay(PendingMutationType.VoidExpenseOffset, bundle(++version, voided = true))
        assertEquals(1, replay.engine.drainOnce().done)
        assertEquals(latest.root.rowVersion, dao.findByServerId("owner", 9)?.rowVersion)
        assertEquals(0, attempts)
        assertOriginalDone(replay)
    }

    suspend fun oldBindingCannotDispatchOrNotify() {
        var binding = testOutboxBinding()
        val replay = replay(PendingMutationType.VoidExpenseOffset, bundle(++version, voided = true)) { binding }
        var attempts = 0
        container.expenseRepository.onConfirmedCommitted = { attempts++ }
        replay.outbox.withBindingTransition { binding = testOutboxBinding(ledgerId = "another-ledger") }
        request = null
        assertEquals(0, replay.engine.drainOnce().attempted)
        assertEquals(null, request)
        assertEquals(0, attempts)
        assertEquals(PendingMutationStatus.Pending.wireValue, replay.rows.rows.getValue(replay.original.id).status)
    }

    suspend fun cacheFailureCannotPublishANotification() {
        var attempts = 0
        container.expenseRepository.onConfirmedCommitted = { attempts++ }
        val replay = replay(PendingMutationType.VoidExpenseOffset, bundle(++version, voided = true))
        database.close()
        assertEquals(1, replay.engine.drainOnce().retryable)
        assertEquals(0, attempts)
        assertEquals(0L, replay.outbox.acceptedReplayRevision.value)
        assertEquals(replay.original.payload, replay.rows.rows.getValue(replay.original.id).payload)
    }

    private suspend fun replay(
        type: PendingMutationType,
        response: ExpenseFactBundleDto,
        binding: () -> OutboxBinding = { testOutboxBinding() },
    ): OffsetReplay {
        val rows = FakePendingMutationDao()
        val outbox = testOutboxRepository(rows, bindingProvider = binding)
        val create = ExpenseOffsetCreateRequestDto(ExpenseOffsetKindDto.Refund, 300, "2026-09-03", "Original refund", 7)
        val isCreate = type == PendingMutationType.CreateExpenseOffset
        val body = if (isCreate) adapters.offsetCreateAdapter.toJson(create) else adapters.offsetVoidAdapter.toJson(
            ExpenseOffsetVoidOutboxPayload("refund-1", "Original void"))
        outbox.enqueue(type, expenseTargetId(9), body, if (isCreate) 7L else 3L, "original-offset-key")
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun createExpenseOffset(id: String, request: ExpenseOffsetCreateRequestDto,
                idempotencyKey: String): ExpenseFactBundleDto {
                assertEquals("9", id)
                assertEquals(create, request)
                this@OffsetPublicationFixture.request = request to idempotencyKey
                return response
            }
            override suspend fun voidExpenseOffset(id: String, offsetPublicId: String,
                request: ExpenseOffsetVoidRequestDto, idempotencyKey: String): ExpenseFactBundleDto {
                assertEquals("9", id)
                assertEquals("refund-1", offsetPublicId)
                assertEquals(ExpenseOffsetVoidRequestDto("Original void", 3), request)
                this@OffsetPublicationFixture.request = request to idempotencyKey
                return response
            }
        }
        val dispatcher = if (isCreate) CreateExpenseOffsetDispatcher({ api }, adapters.offsetCreateAdapter, publishCreate)
            else VoidExpenseOffsetDispatcher({ api }, adapters.offsetVoidAdapter, publishVoid)
        return OffsetReplay(rows, outbox, OutboxDrainEngine(outbox, listOf(dispatcher)), rows.rows.values.single())
    }

    private fun assertOriginalDone(replay: OffsetReplay) {
        val stored = replay.rows.rows.getValue(replay.original.id)
        assertEquals(PendingMutationStatus.Done.wireValue, stored.status)
        assertEquals(replay.original.payload, stored.payload)
        assertEquals(replay.original.expectedRowVersion, stored.expectedRowVersion)
        assertEquals(replay.original.idempotencyKey, stored.idempotencyKey)
        assertEquals(replay.original.ownerKey, stored.ownerKey)
        assertEquals(replay.original.ledgerId, stored.ledgerId)
        assertEquals(replay.original.serverUrl, stored.serverUrl)
        assertEquals(replay.original.idempotencyKey, assertNotNull(request).second)
    }

    private fun bundle(rowVersion: Long, voided: Boolean) = expenseFactBundleDtoFixture(
        root = confirmedExpenseDtoFixture(ConfirmedExpenseFixture(amountCents = 1200, rowVersion = rowVersion)),
        status = if (voided) ExpenseLineageStatusDto.Confirmed else ExpenseLineageStatusDto.PartiallyRefunded,
        lineageHomeNetCents = if (voided) 1200 else 900,
        activeOffsets = if (voided) emptyList() else expenseFactBundleDtoFixture().activeOffsets,
    )

    private fun registeredPublisher(type: PendingMutationType): suspend (String, ExpenseFactBundleDto) -> Unit {
        // Read the production closure; no substitute publisher or new production visibility exists for this test.
        val getter = AppContainer::class.java.getDeclaredMethod("getOutboxDispatchers").apply { isAccessible = true }
        val dispatchers = getter.invoke(container) as List<*>
        val dispatcher = dispatchers.filterIsInstance<OutboxMutationDispatcher>().single { it.type == type }
        return dispatcher.javaClass.getDeclaredField("publishBundle").apply { isAccessible = true }.get(dispatcher)
            as suspend (String, ExpenseFactBundleDto) -> Unit
    }
}

private data class OffsetReplay(
    val rows: FakePendingMutationDao,
    val outbox: OutboxRepository,
    val engine: OutboxDrainEngine,
    val original: com.ticketbox.data.local.PendingMutationEntity,
)
