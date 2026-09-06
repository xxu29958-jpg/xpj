package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.repository.ExpenseCorrectionPayload
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.OutboxWriteBlock
import com.ticketbox.data.repository.PendingExpenseCorrection
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 §4.10: a reaper age-cap expiry is terminal — the FailedCard hides
 * Retry for it (replaying would hit a server-purged idempotency key, and the
 * next drain would just re-reap the row). Other reasons are not age expiry;
 * payload support and protocol recovery are separate decisions.
 */
class SyncStatusFailureTest {

    @Test
    fun `reaper-expired marker is terminal (no retry)`() {
        assertTrue(isExpiredFailure("outbox_row_expired"))
    }

    @Test
    fun `other failure markers stay retryable`() {
        assertFalse(isExpiredFailure("max_attempts_exceeded(10/10): server 503"))
        assertFalse(isExpiredFailure("no_dispatcher_registered:replace_splits"))
        assertFalse(isExpiredFailure(null))
    }

    @Test
    fun `recycled rule category points the user to restore then retry`() {
        assertEquals(
            R.string.sync_status_error_rule_category_deleted,
            syncStatusExactErrorMessageResources["rule_category_deleted"],
        )
    }

    @Test
    fun `protocol refusals explain compatible version recovery`() {
        for (code in listOf("runtime_version_mismatch", "client_upgrade_required")) {
            assertEquals(R.string.sync_status_error_protocol_mismatch, syncStatusExactErrorMessageResources[code])
        }
    }

    @Test
    fun `overview counts come from outbox status`() {
        val overview = syncStatusOverview(
            OutboxStatus(
                queueDepth = 3,
                conflicts = listOf(row(id = 1), row(id = 2)),
                failed = listOf(row(id = 3)),
                quarantinedCount = 4,
            ),
            corrections = emptyList(),
            adjustments = emptyList(),
        )

        assertEquals(3, overview.queuedCount)
        assertEquals(2, overview.conflictCount)
        assertEquals(1, overview.failedCount)
        assertEquals(4, overview.quarantinedCount)
        assertEquals(0, overview.reviewRequiredCount)
        assertEquals(7, overview.needsActionCount)
        assertFalse(overview.isSettled)
    }

    @Test
    fun `overview clamps invalid queue depth and marks settled`() {
        val overview = syncStatusOverview(
            OutboxStatus(
                queueDepth = -1,
                conflicts = emptyList(),
                failed = emptyList(),
            ),
            corrections = emptyList(),
            adjustments = emptyList(),
        )

        assertEquals(0, overview.queuedCount)
        assertEquals(0, overview.reviewRequiredCount)
        assertTrue(overview.isSettled)

        val stopped = com.ticketbox.data.repository.PendingDebtAdjustment(
            row(id = 7).copy(type = PendingMutationType.RecordDebtAdjustment, status = PendingMutationStatus.Abandoned), null,
        )
        val localStop = syncStatusOverview(OutboxStatus(0, emptyList(), emptyList()), emptyList(), listOf(stopped))
        assertEquals(1, localStop.stoppedCount)
        assertEquals(0, localStop.needsActionCount)
        assertEquals(0, localStop.queuedCount)
        assertEquals(0, localStop.failedCount)
        assertFalse(localStop.isSettled, "A local stop is neither delivery confirmation nor unresolved work")
        val otherStatuses = PendingMutationStatus.entries.filter { it != PendingMutationStatus.Abandoned }
            .map { stopped.copy(row = stopped.row.copy(status = it)) }
        assertEquals(0, syncStatusOverview(OutboxStatus(0, emptyList(), emptyList()), emptyList(), otherStatuses).stoppedCount)
    }

    @Test
    fun `owner adoption block replaces misleading network recovery caption`() {
        val overview = syncStatusOverview(
            OutboxStatus(
                queueDepth = 1,
                conflicts = emptyList(),
                failed = emptyList(),
                writeBlock = OutboxWriteBlock.CURRENCY_ADOPTION_REQUIRED,
            ),
            corrections = emptyList(),
            adjustments = emptyList(),
        )

        assertEquals(
            R.string.error_currency_adoption_required,
            overviewCaptionResource(overview),
        )
    }

    @Test
    fun `unproven done requires review without changing the original command`() {
        val original = row(id = 1).copy(
            type = PendingMutationType.CorrectExpense,
            status = PendingMutationStatus.Done,
            payloadJson = "{\"expected_row_version\":0,\"reason\":\"old submission\"}",
            idempotencyKey = "original-key",
        )
        val pending = PendingExpenseCorrection(original, intent = null)
        val overview = syncStatusOverview(OutboxStatus(0, emptyList(), emptyList()), listOf(pending), emptyList())

        assertEquals(1, overview.reviewRequiredCount)
        assertEquals(1, overview.needsActionCount)
        assertEquals(0, overview.queuedCount)
        assertFalse(overview.isSettled)
        assertEquals(original, pending.row)
    }

    @Test
    fun `review count excludes queued failures conflicts and verified done`() {
        val active = listOf(
            PendingMutationStatus.Pending, PendingMutationStatus.InFlight,
            PendingMutationStatus.Conflict, PendingMutationStatus.Failed,
        ).mapIndexed { index, status ->
            PendingExpenseCorrection(
                row(id = index + 1L).copy(type = PendingMutationType.CorrectExpense, status = status),
                intent = null,
            )
        }
        val verified = PendingExpenseCorrection(
            row(id = 5).copy(
                type = PendingMutationType.CorrectExpense,
                status = PendingMutationStatus.Done,
                ownerKey = "owner",
                idempotencyKey = "confirmed-key",
            ),
            intent = ExpenseCorrectionPayload(
                revision = 1,
                expenseId = 5,
                originalMerchant = "Merchant",
                originalCurrencyCode = "CNY",
                originalAmountMinor = 1000L,
                homeCurrencyCode = "CNY",
                ownerKey = "owner",
                ledgerId = "ledger",
                originSessionGeneration = "session",
                originBindingRevision = "binding",
                request = ExpenseCorrectionRequestDto(1L, "confirmed"),
            ),
        )
        assertTrue(verified.delivered)
        val overview = syncStatusOverview(
            OutboxStatus(2, listOf(active[2].row), listOf(active[3].row)), active + verified,
            adjustments = emptyList(),
        )
        assertEquals(0, overview.reviewRequiredCount)
        assertEquals(2, overview.queuedCount)
        assertEquals(1, overview.conflictCount)
        assertEquals(1, overview.failedCount)
        assertEquals(2, overview.needsActionCount)
        assertFalse(overview.isSettled)
        val doneOnly = syncStatusOverview(OutboxStatus(0, emptyList(), emptyList()), listOf(verified), emptyList())
        assertEquals(0, doneOnly.reviewRequiredCount)
        assertTrue(doneOnly.isSettled)
    }

    @Test
    fun `every pending mutation type has an explicit sync label`() {
        assertEquals(
            PendingMutationType.entries.toSet(),
            syncStatusMutationLabelResources.keys,
        )
        assertEquals(
            R.string.sync_status_mutation_unknown,
            syncStatusMutationLabelRes(PendingMutationType.Unknown),
        )
    }

    private fun row(id: Long) = OutboxRow(
        id = id,
        serverUrl = "http://127.0.0.1:8000",
        ledgerId = "ledger",
        type = PendingMutationType.PatchExpense,
        targetId = "expense:$id",
        payloadJson = "{}",
        expectedRowVersion = 1L,
        status = PendingMutationStatus.Conflict,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-07-01T00:00:00Z",
        attemptedAt = null,
        completedAt = null,
    )
}
