package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitInviteRequestDto
import com.ticketbox.data.remote.dto.BillSplitSentDto
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.HttpException
import retrofit2.Response

/** Shared production graph/Room fixture; transport assertions complement the real PostgreSQL replay test. */
@RunWith(AndroidJUnit4::class)
class BillSplitCreationRoomContinuityTest {
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext())
    private val adapters = OutboxAdapterGraph()
    private val calls = mutableListOf<Pair<BillSplitInviteRequestDto, String>>()
    private var loseResponse = true
    private var refusal: String? = null
    private val service = object : ApiService by fixture.network.service {
        override suspend fun createBillSplitInvitation(id: Long, request: BillSplitInviteRequestDto, idempotencyKey: String): BillSplitSentDto {
            calls += request to idempotencyKey
            refusal?.let { code -> throw HttpException(Response.error<Any>(409,
                """{"error":"$code","message":"Synthetic refusal"}""".toResponseBody("application/json".toMediaType()))) }
            if (loseResponse) throw IOException("Response lost after server acceptance")
            return BillSplitSentDto(publicId = "original-invitation", status = "accepted", amountCents = request.amountCents,
                merchantSnapshot = "Original merchant", categorySuggestion = null, expenseTimeSnapshot = null,
                expiresAt = "2026-10-01T00:00:00Z", createdAt = "2026-09-06T00:00:00Z", acceptedAt = "2026-09-06T00:01:00Z",
                rejectedAt = null, cancelledAt = null, expiredAt = null, receiverAccountId = request.receiverAccountId,
                receiverDisplayNameSnapshot = "Receiver", senderExpenseId = id, homeCurrencyCode = "CNY")
        }
    }

    @After fun close() = fixture.close()

    @Test fun originalKeyPayloadAndReceiptSurviveLostResponseAndRoomReopen() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        val source = fixture.network.current.toDomain()
        assertTrue(repository.createBillSplitInvitation(binding, source, 22, "Receiver", 400).isSuccess)
        assertTrue(calls.isEmpty())
        val original = repository.observeBillSplitCreations().first().submissions.single()
        assertEquals(source.rowVersion, original.row.expectedRowVersion)
        assertEquals(1, engine().drainOnce().failed)

        val restarted = fixture.reopen().expenseRepository
        val interrupted = restarted.observeBillSplitCreations().first().submissions.single()
        assertEquals(original.row.payloadJson, interrupted.row.payloadJson)
        assertEquals(original.row.idempotencyKey, interrupted.row.idempotencyKey)
        assertEquals(PendingMutationStatus.Failed, interrupted.row.status)
        assertTrue(!fixture.outbox.resolveFailed(original.row.id, FailedResolution.Retry(source.rowVersion + 1)))
        val unchanged = restarted.observeBillSplitCreations().first().submissions.single()
        assertEquals(original.row.expectedRowVersion, unchanged.row.expectedRowVersion)
        assertEquals(original.row.idempotencyKey, unchanged.row.idempotencyKey)
        assertTrue(restarted.recoverBillSplitCreation(binding, original.row.id, false).isSuccess)
        loseResponse = false
        assertEquals(1, engine().drainOnce().done)
        assertEquals(2, calls.size)
        assertEquals(calls.first(), calls.last())

        val delivered = fixture.reopen().expenseRepository.observeBillSplitCreations().first().submissions.single()
        assertTrue(delivered.delivered)
        assertEquals("original-invitation", delivered.invitation?.publicId)
        assertEquals("accepted", delivered.invitation?.status)
        assertEquals(original.row.payloadJson, delivered.row.payloadJson)
        assertEquals(original.row.idempotencyKey, delivered.row.idempotencyKey)
    }

    @Test fun protocolRefusalPreservesTheUnsentIntentAndDoesNotReportDone() = runBlocking {
        val repository = fixture.reopen().expenseRepository
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        repository.createBillSplitInvitation(binding, fixture.network.current.toDomain(), 22, "Receiver", 400).getOrThrow()
        refusal = "client_upgrade_required"
        assertEquals(1, engine().drainOnce().failed)
        val original = fixture.reopen().expenseRepository.observeBillSplitCreations().first().submissions.single()
        assertEquals(PendingMutationStatus.Failed, original.row.status)
        assertEquals("client_upgrade_required", original.row.lastError)
        assertEquals(null, original.row.receiptJson)
        assertTrue(original.row.idempotencyKey?.isNotBlank() == true)
    }

    private fun engine() = OutboxDrainEngine(outbox = fixture.outbox,
        dispatchers = listOf(CreateBillSplitDispatcher({ service }, adapters.billSplitCreateAdapter, adapters.billSplitReceiptAdapter)),
        maxAttempts = 1)
}
