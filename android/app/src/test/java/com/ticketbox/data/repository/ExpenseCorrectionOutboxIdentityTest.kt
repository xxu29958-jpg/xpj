package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.PendingMutationStatus
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

internal class ExpenseCorrectionOutboxIdentityTest {
    private fun fixedClock(value: String): Clock = Clock.fixed(Instant.parse(value), ZoneOffset.UTC)

    @Test
    fun compositeCorrectionKeepMineCannotReplaceOriginalCommandIdentity() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-09-06T00:00:00Z"))
        val payload = """{"expected_row_version":0,"reason":"校正分摊","splits":[{"member_id":7,"amount_cents":1200}]}"""
        val id = repo.enqueue(PendingMutationType.CorrectExpense, "expense:1", payload, 7L,
            idempotencyKey = "original-correction-key")
        repo.markConflict(id, "state_conflict")
        val original = dao.rows.getValue(id)

        val changed = repo.resolveConflict(id, ConflictResolution.KeepMine(freshToken = 8L))

        assertEquals(false, changed, "a generic fresh-token action has no reviewed replacement correction")
        val retained = dao.rows.getValue(id)
        assertEquals(7L, retained.expectedRowVersion)
        assertEquals("original-correction-key", retained.idempotencyKey)
        assertEquals(payload, retained.payload)
        assertEquals(original.ownerKey, retained.ownerKey)
        assertEquals(original.ledgerId, retained.ledgerId)
        assertEquals(PendingMutationStatus.Conflict.wireValue, retained.status)
    }

    @Test
    fun compositeCorrectionFailedRetryCannotReplaceOriginalCommandIdentity() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-09-06T00:00:00Z"))
        val payload = """{"expected_row_version":0,"reason":"校正明细","items":[{"name":"午餐","amount_cents":1200}]}"""
        val id = repo.enqueue(PendingMutationType.CorrectExpense, "expense:1", payload, 7L,
            idempotencyKey = "original-correction-key")
        repo.markFailed(id, "runtime_version_mismatch")
        val original = dao.rows.getValue(id)

        val changed = repo.resolveFailed(id, FailedResolution.Retry(freshToken = 8L))

        assertEquals(false, changed, "protocol recovery may not mint a different correction against a fresh token")
        val retained = dao.rows.getValue(id)
        assertEquals(7L, retained.expectedRowVersion)
        assertEquals("original-correction-key", retained.idempotencyKey)
        assertEquals(payload, retained.payload)
        assertEquals(original.ownerKey, retained.ownerKey)
        assertEquals(original.ledgerId, retained.ledgerId)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
    }

}
