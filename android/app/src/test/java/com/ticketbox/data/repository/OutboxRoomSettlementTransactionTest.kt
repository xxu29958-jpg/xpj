package com.ticketbox.data.repository

import android.app.Application
import android.database.sqlite.SQLiteException
import androidx.room.Room
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationDoneUpdate
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.SQLiteMode
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
@SQLiteMode(SQLiteMode.Mode.NATIVE)
class OutboxRoomSettlementTransactionTest {

    @Test
    fun roomTransactionMarksDoneAndCascadesEligibleSiblingsOnly() = runBlocking(Dispatchers.IO) {
        val database = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val dao = database.pendingMutationDao()
            val ownerA = testOutboxBinding(ledgerId = "ledger-a")
            val ownerB = testOutboxBinding(
                ledgerId = "ledger-a",
                owner = requireNotNull(
                    OutboxOwnerIdentity.fromOrNull(
                        serverId = "20000000-0000-0000-0000-000000000001",
                        dataGeneration = "20000000-0000-0000-0000-000000000002",
                        accountPublicId = "20000000-0000-0000-0000-000000000003",
                        devicePublicId = "20000000-0000-0000-0000-000000000004",
                    ),
                ),
            )
            var binding = ownerA
            val outbox = testOutboxRepository(dao = dao, bindingProvider = { binding })

            val firstPatch = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k1")
            val siblingPatch = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k2")
            val preservedCorrection = outbox.enqueue(PendingMutationType.CorrectExpense, "expense:42", "{}", 1L, "k3")
            val otherTarget = outbox.enqueue(PendingMutationType.PatchExpense, "expense:99", "{}", 1L, "k4")
            assertTrue(outbox.tryClaim(firstPatch))
            val claimedRow = dao.allRows().single { it.id == firstPatch }.toDomain()

            val conflictSibling = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k5")
            val failedSibling = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k6")
            val doneSibling = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k7")
            outbox.markConflict(conflictSibling, "stale")
            outbox.markFailed(failedSibling, "failed")
            outbox.markDone(doneSibling)

            binding = ownerA.copy(ledgerId = "ledger-b")
            val otherLedgerSibling = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k8")
            binding = ownerB
            val otherOwnerSibling = outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{}", 1L, "k9")
            binding = ownerA.copy(ledgerId = "ledger-b")

            assertTrue(outbox.markDone(firstPatch, OutboxDoneSettlement(acceptedRow = claimedRow, cascadeNewToken = 2L)))

            val rowsById = dao.allRows().associateBy { it.id }
            assertEquals(PendingMutationStatus.Done.wireValue, rowsById.getValue(firstPatch).status)
            assertEquals(2L, rowsById.getValue(siblingPatch).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(preservedCorrection).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(otherTarget).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(conflictSibling).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(failedSibling).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(doneSibling).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(otherLedgerSibling).expectedRowVersion)
            assertEquals(1L, rowsById.getValue(otherOwnerSibling).expectedRowVersion)

            val missingRowUpdated = dao.markDoneAndCascadeToken(
                done = PendingMutationDoneUpdate(id = 99999L, status = PendingMutationStatus.Done.wireValue, completedAt = "2026-05-04T00:00:00.000Z"),
                cascade = preservedTokenCascade(ownerA.ownerStorageKey, ownerA.ledgerId, "expense:42", 9L),
            )
            assertEquals(0, missingRowUpdated)
            assertEquals(2L, dao.allRows().single { it.id == siblingPatch }.expectedRowVersion)
        } finally {
            database.close()
        }
    }

    @Test
    fun roomTransactionRollsBackMarkDoneWhenTokenCascadeThrows() = runBlocking(Dispatchers.IO) {
        val database = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val dao = database.pendingMutationDao()
            val binding = testOutboxBinding()
            val outbox = testOutboxRepository(dao = dao, bindingProvider = { binding })

            val firstId = outbox.enqueue(PendingMutationType.ReplaceSplits, "expense:77", "{}", 1L, "k-rollback-1")
            val siblingId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:77", "{}", 1L, "k-rollback-2")
            outbox.tryClaim(firstId)
            val claimedRow = dao.allRows().single { it.id == firstId }.toDomain()

            database.openHelper.writableDatabase.execSQL(
                """
                CREATE TRIGGER fail_cascade_token
                BEFORE UPDATE OF expectedRowVersion ON pending_mutations
                WHEN NEW.expectedRowVersion = 777
                BEGIN
                    SELECT RAISE(ABORT, 'forced_cascade_failure');
                END
                """.trimIndent(),
            )

            assertFailsWith<SQLiteException> {
                outbox.markDone(firstId, OutboxDoneSettlement(acceptedRow = claimedRow, cascadeNewToken = 777L))
            }

            val rowsById = dao.allRows().associateBy { it.id }
            assertEquals(PendingMutationStatus.InFlight.wireValue, rowsById.getValue(firstId).status)
            assertNull(rowsById.getValue(firstId).completedAt)
            assertEquals(1L, rowsById.getValue(siblingId).expectedRowVersion)
        } finally {
            database.close()
        }
    }

    @Test
    fun roomDaoRefusesFreshTokenRequeueForVoidExpenseOffset() = runBlocking(Dispatchers.IO) {
        val database = Room.inMemoryDatabaseBuilder(RuntimeEnvironment.getApplication(), AppDatabase::class.java).build()
        try {
            val dao = database.pendingMutationDao()
            val binding = testOutboxBinding()
            val outbox = testOutboxRepository(dao = dao, bindingProvider = { binding })
            val id = outbox.enqueue(
                PendingMutationType.VoidExpenseOffset,
                "expense:42",
                """{"offsetPublicId":"refund-1","voidReason":"撤销误记"}""",
                3L,
                "void-room-key",
            )
            outbox.markConflict(id, "state_conflict")
            assertEquals(0, dao.requeueConflictWithFreshToken(id, binding.ownerStorageKey, binding.ledgerId, 9L, "rotated"))
            assertEquals(3L, dao.allRows().single { it.id == id }.expectedRowVersion)

            outbox.markFailed(id, "failed")
            assertEquals(0, dao.requeueFailedWithFreshToken(id, binding.ownerStorageKey, binding.ledgerId, 9L, "rotated"))
            assertEquals(3L, dao.allRows().single { it.id == id }.expectedRowVersion)
            assertEquals("void-room-key", dao.allRows().single { it.id == id }.idempotencyKey)
        } finally {
            database.close()
        }
    }
}
