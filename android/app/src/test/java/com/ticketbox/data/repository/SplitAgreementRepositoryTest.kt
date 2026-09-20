package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitChangeAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeEmptyRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeProposalDto
import java.io.IOException
import java.time.Clock
import java.time.Duration
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class SplitAgreementRepositoryTest {
    @Test fun publishBindsPrincipalAndPersistsBothVersionsBeforeSchedulingWithoutNetwork() = runTest {
        val f = DebtAdjustmentFixture()
        val repo = repository(f)
        val task = DebtTask(f.binding, "original")
        val id = repo.submit(task, create()).getOrThrow()
        val stored = f.dao.rows.getValue(id)
        assertEquals(PendingMutationType.SplitAgreement.wireValue, stored.type)
        assertEquals("debt:original", stored.targetId)
        assertEquals(f.binding.ownerKey, stored.ownerKey)
        assertEquals(listOf(1), f.queueDepthAtSchedule)
        assertTrue(f.api.calls.isEmpty())
        assertEquals(create(), f.adapters.splitAgreementAdapter.fromJson(stored.payload))
        assertFalse(repo.submit(task, create()).isSuccess)
        assertFalse(repo.submit(task.copy(binding = f.binding.copy(bindingRevision = "stale")), create()).isSuccess)
        assertEquals(1, f.dao.rows.size)
    }

    @Test fun pendingOriginalIsVisibleFromReturnTaskWithoutAnAgreementGet() = runTest {
        val f = DebtAdjustmentFixture()
        val repo = repository(f)
        val task = DebtTask(f.binding, "original")
        repo.submit(task, create().copy(returnDebtPublicId = "return")).getOrThrow()
        val pending = repo.observe(task.copy(debtPublicId = "return")).first().single()
        assertEquals("退款后双方重议", repo.describe(pending)?.create?.reason)
        assertEquals("debt:original", pending.targetId)
        assertTrue(repo.observe(task.copy(binding = task.binding.copy(bindingRevision = "another"))).first().isEmpty())
    }

    @Test fun lostResponseReplayKeepsKeyAndBothVersionsThenStoresDoneReceipt() = runTest {
        val f = DebtAdjustmentFixture()
        val task = DebtTask(f.binding, "original")
        val id = repository(f).submit(task, create()).getOrThrow()
        val original = f.dao.rows.getValue(id)
        val calls = mutableListOf<Pair<BillSplitChangeCreateRequestDto, String?>>()
        val api = object : ApiService by f.api {
            override suspend fun createSplitChangeProposal(publicId: String, request: BillSplitChangeCreateRequestDto,
                idempotencyKey: String?): BillSplitChangeProposalDto {
                assertEquals("original", publicId)
                calls += request to idempotencyKey
                if (calls.size == 1) throw IOException("response lost after server acceptance")
                return splitTestProposal()
            }
        }
        val dispatcher = SplitAgreementDispatcher({ api }, f.adapters.splitAgreementAdapter, f.adapters.splitAgreementReceiptAdapter)
        assertEquals(1, OutboxDrainEngine(f.outbox, listOf(dispatcher), now = f.clock::millis).drainOnce().retryable)
        val clock = Clock.offset(f.clock, Duration.ofMinutes(3))
        val restarted = f.newOutbox(clock)
        assertEquals(1, OutboxDrainEngine(restarted, listOf(dispatcher), now = clock::millis).drainOnce().done)
        assertEquals(calls.first(), calls.last())
        assertEquals(original.idempotencyKey, calls.last().second)
        val row = repository(f, restarted).observe(task).first().single()
        assertEquals(PendingMutationStatus.Done, row.status)
        assertEquals(original.payload, row.payloadJson)
        assertNotNull(row.receiptJson)
        assertEquals(SplitAgreementReceipt("proposal", "pending"), f.adapters.splitAgreementReceiptAdapter.fromJson(row.receiptJson!!))
        assertEquals(0, OutboxDrainEngine(restarted, listOf(dispatcher), now = clock::millis).drainOnce().done)
        assertEquals(2, calls.size)
    }

    @Test fun conflictCannotRewriteVersionsOrKeyAndDraftCanBeReconsideredAfterExplicitDrop() = runTest {
        val f = DebtAdjustmentFixture()
        val repo = repository(f)
        val task = DebtTask(f.binding, "original")
        val id = repo.submit(task, create()).getOrThrow()
        val api = object : ApiService by f.api {
            override suspend fun createSplitChangeProposal(publicId: String, request: BillSplitChangeCreateRequestDto,
                idempotencyKey: String?): BillSplitChangeProposalDto = throw HttpException(Response.error<Any>(409,
                """{"error":"state_conflict","message":"已变化"}""".toResponseBody("application/json".toMediaType())))
        }
        val dispatcher = SplitAgreementDispatcher({ api }, f.adapters.splitAgreementAdapter, f.adapters.splitAgreementReceiptAdapter)
        OutboxDrainEngine(f.outbox, listOf(dispatcher), now = f.clock::millis).drainOnce()
        val original = f.dao.rows.getValue(id)
        val row = repo.observe(task).first().single()
        assertEquals(PendingMutationStatus.Conflict, row.status)
        assertFalse(f.outbox.resolveConflict(id, ConflictResolution.KeepMine(99)))
        assertEquals(original, f.dao.rows.getValue(id))
        assertFalse(repo.recover(task, row, false).isSuccess)
        repo.recover(task, row, true).getOrThrow()
        assertTrue(repo.observe(task).first().isEmpty())
    }

    @Test fun refusedShareCannotRetryForeverAndExplicitDropAllowsRevisedDraftWithNewKey() = runTest {
        val f = DebtAdjustmentFixture()
        val repo = repository(f)
        val task = DebtTask(f.binding, "original")
        val id = repo.submit(task, create()).getOrThrow()
        val key = f.dao.rows.getValue(id).idempotencyKey
        val api = object : ApiService by f.api {
            override suspend fun createSplitChangeProposal(publicId: String, request: BillSplitChangeCreateRequestDto,
                idempotencyKey: String?): BillSplitChangeProposalDto = throw HttpException(Response.error<Any>(422,
                """{"error":"split_total_exceeds_parent","message":"超过原单"}""".toResponseBody("application/json".toMediaType())))
        }
        val dispatcher = SplitAgreementDispatcher({ api }, f.adapters.splitAgreementAdapter, f.adapters.splitAgreementReceiptAdapter)
        OutboxDrainEngine(f.outbox, listOf(dispatcher), now = f.clock::millis).drainOnce()
        val row = repo.observe(task).first().single()
        assertEquals(PendingMutationStatus.Failed, row.status)
        assertEquals("split_total_exceeds_parent", row.lastError)
        assertFalse(repo.recover(task, row, false).isSuccess)
        repo.recover(task, row, true).getOrThrow()
        val revised = create().copy(create = create().create!!.copy(newShareAmountCents = 1000))
        val next = repo.submit(task, revised).getOrThrow()
        assertTrue(key != f.dao.rows.getValue(next).idempotencyKey)
        assertEquals(1000L, repo.describe(repo.observe(task).first().single())?.create?.newShareAmountCents)
    }

    @Test fun acceptRejectWithdrawUseTheirOriginalWireOperationAndReceiptWithoutTokenCascade() = runTest {
        val f = DebtAdjustmentFixture()
        val calls = mutableListOf<String>()
        val api = object : ApiService by f.api {
            override suspend fun acceptSplitChangeProposal(publicId: String, proposalPublicId: String,
                request: BillSplitChangeAcceptRequestDto, idempotencyKey: String?) = splitTestAgreement().also {
                assertEquals(BillSplitChangeAcceptRequestDto(7, 8), request); calls += "accept:$publicId:$proposalPublicId:$idempotencyKey"
            }
            override suspend fun rejectSplitChangeProposal(publicId: String, proposalPublicId: String,
                request: BillSplitChangeEmptyRequestDto, idempotencyKey: String?) = splitTestProposal().copy(status = "rejected").also { calls += "reject" }
            override suspend fun withdrawSplitChangeProposal(publicId: String, proposalPublicId: String,
                request: BillSplitChangeEmptyRequestDto, idempotencyKey: String?) = splitTestProposal().copy(status = "withdrawn").also { calls += "withdraw" }
        }
        val dispatcher = SplitAgreementDispatcher({ api }, f.adapters.splitAgreementAdapter, f.adapters.splitAgreementReceiptAdapter)
        for (operation in listOf(SPLIT_ACCEPT, SPLIT_REJECT, SPLIT_WITHDRAW)) {
            val intent = SplitAgreementPayload(operation = operation, originalDebtPublicId = "original", proposalPublicId = "proposal",
                accept = if (operation == SPLIT_ACCEPT) BillSplitChangeAcceptRequestDto(7, 8) else null)
            val row = OutboxRow(1, "https://example.test", "owner", type = PendingMutationType.SplitAgreement,
                targetId = "debt:original", payloadJson = f.adapters.splitAgreementAdapter.toJson(intent),
                expectedRowVersion = intent.expectedRowVersion, status = PendingMutationStatus.Pending, retryCount = 0,
                lastError = null, createdAt = "2026-09-20", attemptedAt = null, completedAt = null, idempotencyKey = "original-key")
            val result = dispatcher.dispatch(row) as DispatchResult.Success
            assertEquals(null, result.newRowVersion)
            assertNotNull(result.receiptJson)
            assertTrue(dispatcher.dispatch(row.copy(targetId = "debt:another")) is DispatchResult.Failure)
        }
        assertEquals(listOf("accept:original:proposal:original-key", "reject", "withdraw"), calls)
    }

    private fun repository(f: DebtAdjustmentFixture, outbox: OutboxRepository = f.outbox) =
        SplitAgreementRepository(f.provider, outbox, f.adapters.splitAgreementAdapter)
    private fun create() = SplitAgreementPayload(operation = SPLIT_CREATE, originalDebtPublicId = "original",
        create = BillSplitChangeCreateRequestDto(2000, -1000, "退款后双方重议", 7, 8))
}
