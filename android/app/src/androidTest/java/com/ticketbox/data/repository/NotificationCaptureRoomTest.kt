package com.ticketbox.data.repository

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.notification.PaymentNotificationParser
import com.ticketbox.notification.PaymentNotificationSnapshot
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
import com.ticketbox.notification.PaymentNotificationResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Actual disk Room and original acceptance transaction, including two independent database connections. */
class NotificationCaptureRoomTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val fixture = ExpenseCorrectionConnectedFixture(context)
    private val expense = requireNotNull(PaymentNotificationParser.parse(PaymentNotificationSnapshot(
        "com.eg.android.AlipayGphone", "交易提醒",
        "你有一笔37.90元的支出，领1元生活缴费红包。使用花呗支付，确认收货的订单请及时还款。",
        null, null, 1792213999283)))
    private val repayment = PaymentNotificationResult.Repayment(RepaymentNotificationDraft(RepaymentDraftSource.Alipay,
        50000, "花呗", "2026-09-30T08:00:00Z"))

    @After fun close() { fixture.close() }

    @Test fun diskReopenKeepsBothOriginalCapturesAndDoneRedeliveryCannotAllocateAnother() = runBlocking {
        fixture.reopen()
        var provider = fixture.notificationDependencies.apiServiceProvider
        val origin = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        val repository = NotificationCaptureRepository(provider, fixture.outbox)
        assertTrue(expense is PaymentNotificationResult.Expense)
        assertEquals(3790L, (expense as PaymentNotificationResult.Expense).draft.amountCents)
        val id = repository.accept(expense, origin, "expense-post").getOrThrow()
        val repaymentId = repository.accept(repayment, origin, "repayment-post").getOrThrow()
        assertNotEquals(id, repaymentId)
        val originals = fixture.pendingDao.allRows().associate { it.id to it.payload }
        val frozen = requireNotNull(NotificationCaptureWire.payload.fromJson(requireNotNull(originals[id])))
        assertTrue(requireNotNull(frozen.fieldEvidence).fragments.any { "37.90" in it.literal })
        assertEquals(expense.fieldEvidence?.fragments?.map { it.literal }, frozen.fieldEvidence?.fragments?.map { it.literal })
        fixture.reopen()
        provider = fixture.notificationDependencies.apiServiceProvider
        val reopened = NotificationCaptureRepository(provider, fixture.outbox)
        assertEquals(originals, fixture.pendingDao.allRows().associate { it.id to it.payload })
        assertEquals(id, reopened.accept(expense, origin, "expense-post").getOrThrow())
        fixture.outbox.markDone(id, receiptJson = NotificationCaptureWire.receipt.toJson(NotificationCaptureReceipt(expenseId = 12)))
        assertEquals(id, reopened.accept(expense, origin, "expense-post").getOrThrow())
        val next = reopened.accept(expense, origin, "same-slot-new-post-time").getOrThrow()
        assertNotEquals(id, next)
        assertEquals(3, fixture.pendingDao.allRows().size)
        assertTrue(reopened.accept(expense, origin.copy(ownerKey = "different-principal"), "other-post").isFailure)
    }

    @Test fun simultaneousListenerDeliveriesShareOneOriginalAcrossRoomConnections() = runBlocking {
        fixture.reopen()
        val provider = fixture.notificationDependencies.apiServiceProvider
        val origin = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        val second = Room.databaseBuilder(context, AppDatabase::class.java, "expense-correction-continuity.db").build()
        try {
            val otherQueue = OutboxRepository(second.pendingMutationDao(), fixture.clock,
                bindingProvider = { provider.currentSession().toOutboxBinding() }, onRowsDeleted = {})
            val ids = listOf(fixture.outbox, otherQueue).map { queue -> async(Dispatchers.IO) {
                NotificationCaptureRepository(provider, queue).accept(expense, origin, "same-post").getOrThrow()
            } }.awaitAll()
            assertEquals(1, ids.distinct().size)
            assertEquals(1, fixture.pendingDao.allRows().size)
        } finally { second.close() }
    }
}
