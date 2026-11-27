package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.PendingDuplicateCandidateDto
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Pending commands preserve the reviewed fact until their original worker accepts them. */
internal class ExpensePendingRepositoryOutboxStateActionsTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test
    fun `confirm admission retains the pending fact and original token`() = runTest {
        assertStateAdmission(PendingMutationType.ConfirmExpense)
    }

    @Test
    fun `reject admission retains the pending fact rather than inventing a rejection`() = runTest {
        assertStateAdmission(PendingMutationType.RejectExpense)
    }

    @Test
    fun `mark duplicate admission does not invent the server review result`() = runTest {
        assertStateAdmission(PendingMutationType.MarkNotDuplicate)
    }

    @Test
    fun `retry OCR admission preserves the current snapshot and schedules the original`() = runTest {
        assertStateAdmission(PendingMutationType.RetryOcr)
    }

    @Test
    fun `region retry keeps source coordinates and identity in the original offline intent`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val repo = buildRepository(ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto())),
            testOutboxRepository(dao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val selection = com.ticketbox.domain.model.OcrRegionSelection("a".repeat(64), listOf(60, 25, 110, 50))
        val accepted = repo.retryOcrAllowingOffline(binding, baseline, selection).getOrThrow()
        val row = dao.rows.values.single()
        val request = requireNotNull(moshi().adapter(ExpenseStateTokenRequest::class.java).fromJson(row.payload))
        assertEquals(selection.imageSha256, request.region?.imageSha256)
        assertEquals(selection.box, request.region?.box)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertEquals(baseline, accepted.expense)
        assertNotNull(row.idempotencyKey)
    }

    @Test
    fun `OCR cannot enqueue an unsupported confirmed or rejected expense`() = runTest {
        val dao = FakePendingMutationDao()
        val api = ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, testOutboxRepository(dao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val region = com.ticketbox.domain.model.OcrRegionSelection("a".repeat(64), listOf(60, 25, 110, 50))
        for (status in listOf("confirmed", "rejected")) {
            for (selection in listOf(null, region)) {
                val result = repo.retryOcrAllowingOffline(binding, baselineExpense().copy(status = status), selection)
                assertTrue(result.isFailure, "Only a pending expense can request OCR")
            }
        }
        assertTrue(dao.rows.isEmpty(), "A rejected action must not be reported as an accepted Outbox request")
        assertNull(api.lastRetryOcrIdempotencyKey)
    }

    private suspend fun assertStateAdmission(type: PendingMutationType) {
        val baseline = successExpenseDto().copy(status = "pending", duplicateStatus = "suspected", duplicateOfId = 81L,
            duplicateCandidates = listOf(PendingDuplicateCandidateDto("displayed-pair-decision", 81L,
                score = 0.8, algorithmVersion = "duplicate-candidate-v2"))).toEntity("owner").toDomain()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val success = ApiResult.Success(successExpenseDto())
        val api = ApiServiceStub(confirmExpenseResult = success, rejectExpenseResult = success,
            markNotDuplicateResult = success, retryOcrResult = success)
        val repo = buildRepository(api, outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val accepted = when (type) {
            PendingMutationType.ConfirmExpense -> repo.confirmExpenseAllowingOffline(binding, baseline)
            PendingMutationType.RejectExpense -> repo.rejectExpenseAllowingOffline(binding, baseline)
            PendingMutationType.MarkNotDuplicate -> repo.markNotDuplicateAllowingOffline(binding, baseline)
            PendingMutationType.RetryOcr -> repo.retryOcrAllowingOffline(binding, baseline)
            else -> error("Unexpected state command")
        }.getOrThrow()
        val row = dao.rows.values.single()
        assertEquals(listOf(row.id), accepted.rowIds)
        assertEquals(baseline, accepted.expense)
        assertEquals(type.wireValue, row.type)
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(binding.ownerKey, row.ownerKey)
        assertEquals(binding.ledgerId, row.ledgerId)
        assertEquals(binding.serverUrl, row.serverUrl)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        val request = requireNotNull(moshi().adapter(ExpenseStateTokenRequest::class.java).fromJson(row.payload))
        assertEquals(0L, request.expectedRowVersion)
        val pairDecision = when (type) {
            PendingMutationType.RejectExpense, PendingMutationType.MarkNotDuplicate -> "displayed-pair-decision"
            else -> null
        }
        assertEquals(pairDecision, request.duplicateDecisionPublicId)
        assertNotNull(row.idempotencyKey)
        assertNull(api.lastConfirmIdempotencyKey)
        assertNull(api.lastRejectIdempotencyKey)
        assertNull(api.lastMarkNotDuplicateIdempotencyKey)
        assertNull(api.lastRetryOcrIdempotencyKey)
    }

    @Test
    fun `confirm waits behind a persisted save with both original tokens unchanged`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val api = ApiServiceStub(confirmExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val saved = repo.saveExpenseAllowingOffline(binding, baseline.id, draft, baseline).getOrThrow()
        val confirmed = repo.confirmExpenseAllowingOffline(binding, baseline).getOrThrow()
        val rows = dao.rows.values.toList()
        assertEquals(listOf(PendingMutationType.PatchExpense.wireValue, PendingMutationType.ConfirmExpense.wireValue), rows.map { it.type })
        assertEquals(rows.map { it.id }, saved.rowIds + confirmed.rowIds)
        assertEquals(listOf(baseline.rowVersion, baseline.rowVersion), rows.map { it.expectedRowVersion })
        assertEquals("pending", confirmed.expense.status)
        assertNull(api.lastConfirmIdempotencyKey)
    }

    @Test
    fun `bulk confirmation preserves each original without publishing confirmed facts`() = runTest {
        val expenses = listOf(baselineExpense(), baselineExpense().copy(id = 43L, publicId = "second-expense", rowVersion = 6L))
        val dao = FakePendingMutationDao()
        val api = ApiServiceStub(confirmExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(api, testOutboxRepository(dao))
        val accepted = repo.confirmExpenses(requireNotNull(repo.captureDeferredLedgerBinding()), expenses).getOrThrow()
        val rows = dao.rows.values.toList()
        assertEquals(listOf("expense:42", "expense:43"), rows.map { it.targetId })
        assertEquals(listOf(1L, 6L), rows.map { it.expectedRowVersion })
        assertTrue(rows.all { it.type == PendingMutationType.ConfirmExpense.wireValue && it.status == PendingMutationStatus.Pending.wireValue })
        assertEquals(2, rows.mapNotNull { it.idempotencyKey }.distinct().size)
        assertEquals(rows.map { it.id }, accepted.flatMap { it.rowIds })
        assertEquals(expenses, accepted.map { it.expense })
        assertNull(api.lastConfirmIdempotencyKey)
    }

    @Test
    fun `acknowledge IOException returns Queued acknowledged-projection + enqueues row`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(extras = ApiServiceStubExtras(acknowledgeException = IOException("net out")))
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current)
            .getOrThrow() as ItemsAckOutcome.Queued

        // Optimistic projection flips the items-sum status to acknowledged.
        assertEquals("mismatch_acknowledged", outcome.items.itemsSumStatus)
        assertEquals(1, dao.rows.size)
        val row = dao.rows.values.single()
        assertEquals(PendingMutationType.AcknowledgeItemsMismatch.wireValue, row.type)
        assertEquals("expense:${baseline.id}", row.targetId)
        assertEquals(baseline.rowVersion, row.expectedRowVersion)
        assertTrue(
            baseline.updatedAt !in row.payload,
            "payload must NOT embed the token: ${row.payload}",
        )
        // ADR-0042: direct attempt + enqueued row share one intent-time key.
        assertNotNull(row.idempotencyKey, "AcknowledgeItemsMismatch row must carry an idempotency key")
        assertEquals(api.lastAcknowledgeIdempotencyKey, row.idempotencyKey)
    }

    @Test
    fun `acknowledge direct 2xx returns Synced, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        // acknowledgeException = null → success path.
        val api = ApiServiceStub()
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val outcome = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current).getOrThrow()

        assertTrue(outcome is ItemsAckOutcome.Synced)
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `acknowledge HttpException 409 surfaces as failure, no enqueue`() = runTest {
        val baseline = baselineExpense()
        val current = mismatchKnownItems()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val adapter = moshi().adapter(ExpenseStateTokenRequest::class.java)
        val api = ApiServiceStub(
            extras = ApiServiceStubExtras(
                acknowledgeException = httpException(409, """{"error":"state_conflict","message":"账单已修改"}"""),
            ),
        )
        val repo = buildRepository(api, outbox, stateTokenAdapter = adapter)

        val result = repo.acknowledgeItemsMismatchAllowingOffline(baseline, current)

        assertTrue(result.isFailure, "409 must surface, not silently queue")
        assertEquals(0, dao.rows.size)
    }

    @Test
    fun `dropping a failed OCR region command persists abandoned tombstone across repository restart`() = runTest {
        val baseline = baselineExpense()
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val repo = buildRepository(ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto())), outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val selection = com.ticketbox.domain.model.OcrRegionSelection("a".repeat(64), listOf(60, 25, 110, 50))

        val accepted = repo.retryOcrAllowingOffline(binding, baseline, selection).getOrThrow()
        val rowId = accepted.rowIds.single()
        outbox.markFailed(rowId, "ocr_region_no_text")

        val dropped = outbox.resolveFailed(rowId, FailedResolution.Drop)
        assertTrue(dropped)
        assertEquals(PendingMutationStatus.Abandoned.wireValue, dao.rows.getValue(rowId).status)
        assertTrue(outbox.observeStatus().first().failed.isEmpty())

        // Same-process observation sees droppedRowIds without listing abandoned rows as active commands.
        val observation = repo.observeExpenseCommands().first()
        assertEquals(binding, observation.access?.binding)
        assertTrue(observation.commands.isEmpty())
        assertEquals(setOf(rowId), observation.droppedRowIds)

        // Simulated process death: brand-new OutboxRepository + ExpensePendingRepository over the same DAO.
        val restartedOutbox = testOutboxRepository(dao)
        val restartedRepo = buildRepository(ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto())), restartedOutbox)
        val restartedObservation = restartedRepo.observeExpenseCommands().first()
        assertEquals(binding, restartedObservation.access?.binding)
        assertTrue(restartedObservation.commands.isEmpty())
        assertEquals(setOf(rowId), restartedObservation.droppedRowIds)

        // Age-paused RetryOcr rows still cannot be dropped or abandoned.
        val expiredAccepted = restartedRepo.retryOcrAllowingOffline(binding, baseline, selection).getOrThrow()
        val expiredRowId = expiredAccepted.rowIds.single()
        restartedOutbox.markFailed(expiredRowId, "outbox_row_expired")
        assertTrue(!restartedOutbox.resolveFailed(expiredRowId, FailedResolution.Drop))
        assertEquals(PendingMutationStatus.Failed.wireValue, dao.rows.getValue(expiredRowId).status)

        restartedOutbox.clearAll()
        val afterClear = restartedRepo.observeExpenseCommands().first()
        assertTrue(afterClear.droppedRowIds.isEmpty())
    }

    @Test
    fun `dropping a failed PatchExpense does not propagate droppedRowIds and clearing amount clears optimistic homeAmountCents`() = runTest {
        val legacyBaseline = successExpenseDto().copy(
            status = "pending",
            amountCents = 1789L,
            originalCurrencyCode = "CNY",
            originalAmountMinor = null,
        ).toDomain()
        assertEquals(1789L, legacyBaseline.homeAmountCents)

        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val repo = buildRepository(ApiServiceStub(), outbox)
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())

        val clearDraft = draft.copy(
            amountCents = null,
            originalAmountMinor = null,
            clearAmount = true,
            merchant = "B",
        )
        val accepted = repo.saveExpenseAllowingOffline(binding, legacyBaseline.id, clearDraft, legacyBaseline).getOrThrow()
        assertNull(accepted.expense.amountCents)
        assertNull(accepted.expense.originalAmountMinor)
        assertNull(accepted.expense.homeAmountCents)
        assertEquals("待填写金额", com.ticketbox.presentation.formatExpensePrimaryAmount(accepted.expense))

        val patchRowId = accepted.rowIds.single()
        outbox.markFailed(patchRowId, "validation_error")
        assertTrue(outbox.resolveFailed(patchRowId, FailedResolution.Drop))

        val observation = repo.observeExpenseCommands().first()
        assertTrue(observation.droppedRowIds.isEmpty())
    }

    // endregion
}
