package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import java.io.IOException
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.first
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ManualCreationAdmissionRoomTest {
    private var writes = 0
    private var loseAck = true
    private var receipt: ExpenseDto? = null
    private lateinit var sendingApi: ApiService
    private val requests = mutableListOf<ExpenseManualCreateRequestDto>()
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext<Context>()) { api ->
        object : ApiService by api {
            override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
                writes++
                requests += request
                if (loseAck) throw IOException("ACK lost")
                return requireNotNull(receipt)
            }
        }.also { sendingApi = it }
    }
    private val draft = ExpenseDraft(amountCents = 1200, originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1200, ledgerHomeCurrency = CurrencyCode.CNY, merchant = "Manual",
        category = "其他", note = null, expenseTime = "2026-09-06T00:00:00Z", tags = null,
        valueScore = null, regretScore = null)

    @After fun close() { fixture.close() }

    @Test fun crossDaoPublicationFailureRollsBackBothTablesAndDoesNotSchedule() = runBlocking {
        fixture.reopen()
        val entity = draft.toLocalCreateEntity("correction-ledger", "rollback-ref")
        val result = runCatching {
            val payload = OutboxAdapterGraph().manualCreateAdapter.toJson(draft.toManualCreateRequest("rollback-ref"))
            fixture.outbox.enqueue(boundRequest = null,
                intent = PendingMutationIntent(PendingMutationType.CreateExpense, "expense:local:rollback-ref", payload, 0),
                afterPersisted = {
                    fixture.expenseDao.insert(entity)
                    throw IOException("Publication failed after the expense insert")
                })
        }
        assertTrue(result.isFailure)
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.expenseDao.getConfirmed("correction-ledger").isEmpty())
        assertEquals(0, fixture.schedules)
        fixture.reopen()
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.expenseDao.getConfirmed("correction-ledger").isEmpty())
    }

    @Test fun repositoryReturnsTheDurableOriginalBeforeTransportAndReopensWithTheSameLocalIdentity() = runBlocking {
        val graph = fixture.reopen()
        val expense = graph.expenseRepository.createManualExpense(draft).getOrThrow()
        assertEquals(0, writes)
        assertTrue(expense.id < 0)
        assertTrue(expense.pendingSync)
        assertNotNull(expense.clientRef)
        val original = fixture.stored().single()
        val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(requireNotNull(original["payload"])))
        assertEquals(expense.clientRef, request.clientRef)
        assertEquals("CNY", request.homeCurrencyCode)
        assertEquals("12.00", request.originalAmount)
        assertEquals(1, fixture.schedules)
        val reopened = fixture.reopen().expenseRepository.fetchExpenseFromLocalCache(expense.id).getOrThrow()
        assertEquals(expense.id, reopened.id)
        assertEquals(expense.clientRef, reopened.clientRef)
        assertEquals(original, fixture.stored().single())
        assertEquals(0, writes)
    }

    @Test fun originalCreationReceiptOnlyPromotesIdentityAndCannotReplaceNewerCanonicalMoney() = runBlocking {
        fixture.reopen()
        val original = fixture.network.current.copy(id = 71, publicId = "created-71", rowVersion = 1,
            homeCurrency = "CNY", originalCurrencyCode = "CNY", originalAmountMinor = 1200, amountCents = 1200)
        val local = draft.toLocalCreateEntity("correction-ledger", "same-ref")
        fixture.expenseDao.insert(local)
        val latest = original.copy(rowVersion = 2, amountCents = 3400, originalAmountMinor = 3400)
        fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", latest.toEntity("correction-ledger"))

        fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", original.toEntity("correction-ledger").copy(clientRef = "same-ref"))

        val canonical = fixture.expenseDao.getConfirmed("correction-ledger").single()
        assertEquals(71L, canonical.serverId)
        assertEquals(2L, canonical.rowVersion)
        assertEquals(3400L, canonical.originalAmountMinor)
        assertEquals("same-ref", canonical.clientRef)
        assertFalse(canonical.toDomain().pendingSync)
        // Repeated ACK delivery after promotion also preserves the newer canonical row.
        fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", original.toEntity("correction-ledger").copy(clientRef = "same-ref"))
        assertEquals(canonical, fixture.expenseDao.getConfirmed("correction-ledger").single())
        fixture.expenseDao.clearForLedger("correction-ledger")
        fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", latest.toEntity("correction-ledger"))
        fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", original.toEntity("correction-ledger").copy(clientRef = "same-ref"))
        val restored = fixture.expenseDao.getConfirmed("correction-ledger").single()
        assertEquals("same-ref", restored.clientRef)
        assertEquals(2L, restored.rowVersion)
        assertEquals(3400L, restored.originalAmountMinor)
    }

    @Test fun lostAckReopensTheSameOriginalWithoutRewritingSuccessorTokens() = runBlocking {
        val created = fixture.reopen().expenseRepository.createManualExpense(draft).getOrThrow()
        val original = fixture.stored().single()
        val rowId = requireNotNull(original["id"]).toLong()
        receipt = fixture.network.current.copy(id = 71, publicId = "receipt-71", rowVersion = 3, source = "手动记账",
            homeCurrency = "CNY", originalCurrencyCode = "CNY", originalAmountMinor = 1200, amountCents = 1200)
        assertEquals(1, engine().drainOnce().failures)
        assertEquals(1, writes)
        fixture.reopen()
        fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", requireNotNull(receipt)
            .copy(rowVersion = 4, amountCents = 9900, originalAmountMinor = 9900).toEntity("correction-ledger"))
        val target = "expense:local:${created.clientRef}"
        val firstEdit = fixture.outbox.enqueue(PendingMutationType.PatchExpense, target, "{\"original\":1}", 0, "first-edit-key")
        val basedEdit = fixture.outbox.enqueue(PendingMutationType.PatchExpense, target, "{\"original\":2}", 6, "based-edit-key")
        fixture.outbox.resolveFailed(rowId, FailedResolution.Retry())
        loseAck = false

        assertEquals(1, engine().drainOnce().done)

        assertEquals(2, requests.size)
        assertEquals(requests.first(), requests.last())
        assertEquals(created.clientRef, requests.last().clientRef)
        val rows = fixture.stored().associateBy { requireNotNull(it["id"]).toLong() }
        assertEquals("0", rows.getValue(firstEdit)["expectedRowVersion"])
        assertEquals("6", rows.getValue(basedEdit)["expectedRowVersion"])
        for (column in listOf("payload", "idempotencyKey", "ownerKey", "ledgerId", "serverUrl", "expectedRowVersion")) {
            assertEquals(original[column], rows.getValue(rowId)[column])
        }
        val fact = fixture.expenseDao.getConfirmed("correction-ledger").single()
        assertEquals(4L, fact.rowVersion)
        assertEquals(9900L, fact.originalAmountMinor)
        assertEquals(created.clientRef, fact.clientRef)
        val completed = fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true).first().single()
        val originalView = requireNotNull(fixture.graph.expenseRepository.describeManualCreation(completed))
        assertEquals(71L, originalView.acceptedExpenseId)
        assertEquals("12.00", originalView.request?.originalAmount)
        for (unverified in listOf(null, "{}", "{\"expenseId\":0}")) {
            assertNull(fixture.graph.expenseRepository.describeManualCreation(completed.copy(receiptJson = unverified))?.acceptedExpenseId)
        }
        // A later GET does not preserve client_ref, and clearing read caches must not erase acceptance.
        fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", fact.copy(clientRef = null))
        assertEquals(71L, fixture.graph.expenseRepository.describeManualCreation(completed)?.acceptedExpenseId)
        fixture.expenseDao.clearForLedger("correction-ledger")
        fixture.reopen()
        val reopened = fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true).first().single()
        assertEquals(71L, fixture.graph.expenseRepository.describeManualCreation(reopened)?.acceptedExpenseId)
        assertEquals(completed.receiptJson, reopened.receiptJson)
    }

    @Test fun stoppingRollsBackTogetherAndNeverDeletesAnAlreadyPromotedCanonicalFact() = runBlocking {
        val graph = fixture.reopen()
        val created = graph.expenseRepository.createManualExpense(draft).getOrThrow()
        val row = fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense)).first().single()
        fixture.outbox.markFailed(row.id, MANUAL_CREATE_RECEIPT_REVIEW)
        val failed = fixture.outbox.observeStatus().first().failed.single()
        val original = fixture.stored().single()
        val rollback = runCatching {
            fixture.pendingDao.deleteAndPublish(failed.id, requireNotNull(failed.ownerKey), failed.ledgerId, failed.status.wireValue) {
                fixture.expenseDao.deleteByLocalId(-created.id)
                throw IOException("Stop publication failed")
            }
        }
        assertTrue(rollback.isFailure)
        assertEquals(original, fixture.stored().single())
        assertEquals(created.clientRef, fixture.expenseDao.getConfirmed("correction-ledger").single().clientRef)
        graph.expenseRepository.stopManualCreation(failed).getOrThrow()
        assertTrue(fixture.stored().isEmpty())
        assertTrue(fixture.expenseDao.getConfirmed("correction-ledger").isEmpty())

        val another = graph.expenseRepository.createManualExpense(draft).getOrThrow()
        val again = fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense)).first().single()
        fixture.outbox.markFailed(again.id, MANUAL_CREATE_RECEIPT_REVIEW)
        val canonical = fixture.network.current.copy(id = 71, publicId = "fact-71", rowVersion = 5)
            .toEntity("correction-ledger").copy(clientRef = another.clientRef)
        fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", canonical)
        graph.expenseRepository.stopManualCreation(fixture.outbox.observeStatus().first().failed.single()).getOrThrow()
        assertTrue(fixture.stored().isEmpty())
        val retained = fixture.expenseDao.getConfirmed("correction-ledger").single()
        assertEquals(71L, retained.serverId)
        assertEquals(5L, retained.rowVersion)
    }

    private fun engine(): OutboxDrainEngine {
        val create = CreateExpenseDispatcher({ sendingApi }, OutboxAdapterGraph().manualCreateAdapter) { ledger, ref, value ->
            fixture.expenseDao.applyLocalCreateServerIdentity(ledger, value.toEntity(ledger).copy(clientRef = ref))
        }
        val edit = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult = DispatchResult.Failure("Review captured edit")
        }
        return OutboxDrainEngine(fixture.outbox, listOf(create, edit), maxAttempts = 1, now = fixture.clock::millis)
    }
}
