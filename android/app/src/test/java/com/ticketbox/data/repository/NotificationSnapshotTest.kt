package com.ticketbox.data.repository

import com.ticketbox.notification.PaymentNotificationParser
import com.ticketbox.notification.PaymentNotificationSnapshot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

internal class NotificationSnapshotTest {
    private fun cards(vararg amounts: String) = PaymentNotificationParser.parseCards(PaymentNotificationSnapshot(
        "com.eg.android.alipaygphone", "支付宝", null, null, null, 1_793_524_622_000,
        amounts.map { "你有一笔${it}元的支出。" }))
    private fun delivery(number: Long) = NotificationSnapshotDelivery("slot", "delivery-$number", number)
    private fun CaptureFixture.captures() = dao.rows.values.flatMap {
        val payload = requireNotNull(NotificationCaptureWire.payload.fromJson(it.payload))
        payload.captures.ifEmpty { listOf(payload) }
    }

    @Test fun growingInboxKeepsSingleAndBatchIdentitiesThroughRepositoryRecreation() = runTest {
        val f = CaptureFixture()
        f.repository.acceptSnapshot(cards("10.00"), f.binding, delivery(1)).getOrThrow()
        val first = f.dao.rows.values.single()
        f.repository.acceptSnapshot(cards("10.00", "12.90"), f.binding, delivery(2)).getOrThrow()
        val cold = NotificationCaptureRepository(f.provider, f.newOutbox(), f.snapshots)
        cold.acceptSnapshot(cards("10.00", "12.90", "29.33"), f.binding, delivery(3)).getOrThrow()
        cold.acceptSnapshot(cards("10.00", "12.90", "29.33"), f.binding, delivery(3)).getOrThrow()
        assertEquals(listOf(1000L, 1290L, 2933L), f.captures().map { it.originalAmountMinor })
        assertEquals(first, f.dao.rows[first.id])
        f.api.offline = false
        f.dao.runnableBatches += f.dao.rows.keys.toList()
        f.engine().drainOnce()
        assertEquals(3, f.api.accepted.size)
    }

    @Test fun identicalOccurrencesRemainSeparateAndRemovalStartsANewSourceLifetime() = runTest {
        val f = CaptureFixture()
        f.repository.acceptSnapshot(cards("10.00", "10.00"), f.binding, delivery(1)).getOrThrow()
        f.repository.acceptSnapshot(cards("10.00", "10.00", "10.00"), f.binding, delivery(2)).getOrThrow()
        assertEquals(3, f.captures().size)
        f.repository.closeSnapshot("slot", "delivery-2").getOrThrow()
        f.repository.acceptSnapshot(cards("10.00", "10.00"), f.binding, delivery(3)).getOrThrow()
        assertEquals(5, f.captures().map { it.notificationKey }.distinct().size)
    }

    @Test fun recoveredDeliveryKeepsItsOriginalPrincipalAndOnlyNewCardsBelongToTheNewBinding() = runTest {
        val f = CaptureFixture()
        val originalBinding = f.binding
        f.repository.acceptSnapshot(cards("10.00", "12.90"), originalBinding, delivery(1)).getOrThrow()
        val original = f.dao.rows.values.single()
        f.session.rebindAsDifferentAccountForFixture("另一人", "other-ledger", "另一本", "另一台", "other-token")
        f.repository.acceptSnapshot(cards("10.00", "12.90"), f.binding, delivery(1)).getOrThrow()
        assertEquals(listOf(original), f.dao.rows.values.toList())
        f.repository.acceptSnapshot(cards("10.00", "12.90", "29.33"), f.binding, delivery(2)).getOrThrow()
        assertEquals(original, f.dao.rows[original.id])
        assertEquals(f.binding.ownerKey, f.dao.rows.values.last().ownerKey)
        assertEquals(2933L, f.captures().last().originalAmountMinor)
        assertEquals(3, f.captures().size)
        assertEquals(0, f.api.calls)
    }

    @Test fun legacyOriginalAlsoBlocksRecoveryIntoAnotherPrincipal() = runTest {
        val f = CaptureFixture()
        val parsed = cards("10.00").single()
        f.repository.accept(parsed.result, f.binding, "delivery-1").getOrThrow()
        val original = f.dao.rows.values.single()
        f.session.rebindAsDifferentAccountForFixture("另一人", "other-ledger", "另一本", "另一台", "other-token")
        f.repository.acceptSnapshot(listOf(parsed), f.binding, delivery(1)).getOrThrow()
        assertEquals(listOf(original), f.dao.rows.values.toList())
    }

    @Test fun newSinglePostsNeverCollapseAndFailedAcceptanceDoesNotAdvanceTheJournal() = runTest {
        val f = CaptureFixture()
        f.repository.acceptSnapshot(cards("10.00"), f.binding, delivery(1)).getOrThrow()
        val previous = f.snapshots.notificationSnapshot("slot")
        f.dao.beforeInsert = { error("storage failure") }
        assertTrue(f.repository.acceptSnapshot(cards("10.00"), f.binding, delivery(2)).isFailure)
        assertEquals(previous, f.snapshots.notificationSnapshot("slot"))
        f.dao.beforeInsert = null
        f.repository.acceptSnapshot(cards("10.00"), f.binding, delivery(2)).getOrThrow()
        assertEquals(2, f.captures().size)
    }
}
