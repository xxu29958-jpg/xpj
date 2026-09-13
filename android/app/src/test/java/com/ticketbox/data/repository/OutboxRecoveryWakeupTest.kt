package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.test.runTest
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@RunWith(Parameterized::class)
internal class OutboxRecoveryWakeupTest(private val conflict: Boolean, private val drop: Boolean) {
    @Test
    fun acceptedRecoveryNotifiesAfterTheConditionalChangeAndStaleRecoveryDoesNot() = runTest {
        val dao = FakePendingMutationDao()
        var armed = false
        val notifications = mutableListOf<List<String>>()
        val outbox = testOutboxRepository(dao, onEnqueued = {
            if (armed) notifications += dao.rows.values.map { it.status }
        })
        val id = outbox.enqueue(PendingMutationType.PatchExpense, "expense:9", "{}", 3, "original-key")
        if (conflict) outbox.markConflict(id, "Current fact changed") else outbox.markFailed(id, "Connection unavailable")
        armed = true

        assertTrue(recover(outbox, id))

        val committed = if (drop) emptyList() else listOf(PendingMutationStatus.Pending.wireValue)
        assertEquals(listOf(committed), notifications, "The recovery owner must publish the committed state")
        assertFalse(recover(outbox, id))
        assertEquals(listOf(committed), notifications)
    }

    private suspend fun recover(outbox: OutboxRepository, id: Long): Boolean = if (conflict) {
        outbox.resolveConflict(id, if (drop) ConflictResolution.DropMine else ConflictResolution.KeepMine(4))
    } else {
        outbox.resolveFailed(id, if (drop) FailedResolution.Drop else FailedResolution.Retry())
    }

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "conflict={0}, drop={1}")
        fun actions() = listOf(arrayOf(false, false), arrayOf(false, true), arrayOf(true, false), arrayOf(true, true))
    }
}
