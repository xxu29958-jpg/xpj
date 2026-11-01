package com.ticketbox.data.repository

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.notification.PaymentNotificationParser
import com.ticketbox.notification.PaymentNotificationSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationSnapshotRoomTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val fixture = ExpenseCorrectionConnectedFixture(context)
    private fun cards(vararg amounts: String) = PaymentNotificationParser.parseCards(PaymentNotificationSnapshot(
        "com.eg.android.alipaygphone", "支付宝", null, null, null, 1_793_524_622_000,
        amounts.map { "你有一笔${it}元的支出。" }))
    private fun delivery(number: Long) = NotificationSnapshotDelivery("slot", "source-$number", number)
    @After fun close() { fixture.close() }

    @Test fun coldRecoveryKeepsTheOriginalLedgerAndOnlyAddsTheNewCard() = runBlocking {
        fixture.reopen()
        var provider = fixture.notificationDependencies.apiServiceProvider
        var binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        NotificationCaptureRepository(provider, fixture.outbox, fixture.notificationSnapshots)
            .acceptSnapshot(cards("10.00", "12.90"), binding, delivery(1)).getOrThrow()
        val original = fixture.pendingDao.allRows().single()
        fixture.switchLedger()
        fixture.reopen()
        provider = fixture.notificationDependencies.apiServiceProvider
        binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        val repository = NotificationCaptureRepository(provider, fixture.outbox, fixture.notificationSnapshots)
        repository.acceptSnapshot(cards("10.00", "12.90"), binding, delivery(1)).getOrThrow()
        assertEquals(listOf(original), fixture.pendingDao.allRows())
        repository.acceptSnapshot(cards("10.00", "12.90", "29.33"), binding, delivery(2)).getOrThrow()
        val rows = fixture.pendingDao.allRows()
        assertEquals(2, rows.size)
        assertEquals(original, rows.first())
        assertEquals(binding.ledgerId, rows.last().ledgerId)
        assertEquals(2933L, requireNotNull(NotificationCaptureWire.payload.fromJson(rows.last().payload)).originalAmountMinor)
        fixture.reopen()
        assertEquals(rows, fixture.pendingDao.allRows())
        assertEquals("source-2", fixture.notificationSnapshots.notificationSnapshot("slot")?.deliveryKey)
    }

    @Test fun independentRoomConnectionsPublishOneSnapshotAndPreserveEqualPriceOccurrences() = runBlocking {
        fixture.reopen()
        val provider = fixture.notificationDependencies.apiServiceProvider
        val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        val second = Room.databaseBuilder(context, AppDatabase::class.java, "expense-correction-continuity.db").build()
        try {
            val other = OutboxRepository(second.pendingMutationDao(), fixture.clock,
                bindingProvider = { provider.currentSession().toOutboxBinding() }, onRowsDeleted = {})
            val ids = listOf(fixture.outbox to fixture.notificationSnapshots, other to second.notificationSnapshotDao()).map { (queue, snapshots) -> async(Dispatchers.IO) {
                NotificationCaptureRepository(provider, queue, snapshots).acceptSnapshot(cards("10.00", "10.00"), binding, delivery(1)).getOrThrow()
            } }.awaitAll()
            assertEquals(1, ids.distinct().size)
            val payload = requireNotNull(NotificationCaptureWire.payload.fromJson(fixture.pendingDao.allRows().single().payload))
            assertEquals(2, payload.captures.map { it.notificationKey }.distinct().size)
            assertTrue(payload.captures.all { it.originalAmountMinor == 1000L })
            assertEquals(ids.first(), fixture.notificationSnapshots.notificationSnapshot("slot")?.originalId)
        } finally { second.close() }
    }
}
