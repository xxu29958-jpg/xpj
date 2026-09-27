package com.ticketbox.data.repository

import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DebtRepaymentVoidRepositoryTest {
    @Test fun singlePaymentVoidCarriesParentVersionTargetReasonAndIdempotencyKey() = runTest {
        val fixture = DirectRepaymentTestFixture()
        fixture.api.current = fixture.api.current.copy(homeCurrencyCode = "JPY")
        val debt = fixture.api.current.toDomain()
        fixture.api.loseResponse = false
        fixture.repository.saveRepaymentVoid(fixture.binding, debt, "payment-7", "  重复记录  ").getOrThrow()
        val pending = fixture.pending()
        assertEquals("payment-7", pending.repaymentVoid?.request?.repaymentPublicId)
        assertEquals("重复记录", pending.repaymentVoid?.request?.reason)
        assertEquals(1L, pending.intent?.expectedRowVersion)
        assertTrue(!pending.row.idempotencyKey.isNullOrBlank())
        assertTrue(fixture.api.voidCalls.isEmpty())
        assertEquals(1, fixture.engine().drainOnce().done)
        val receipt = fixture.adapters.debtVoidReceiptAdapter.fromJson(fixture.dao.rows.values.single().receiptJson!!)
        assertEquals("JPY", receipt?.homeCurrencyCode)
        assertEquals(2L, receipt?.rowVersion)
    }

    @Test fun viewerCannotSendTheNewCommand() = runTest {
        val fixture = DirectRepaymentTestFixture(role = "viewer")
        assertTrue(fixture.repository.saveRepaymentVoid(fixture.binding, fixture.debt, "payment-7", "重复记录").isFailure)
        assertTrue(fixture.dao.rows.isEmpty())
        assertTrue(fixture.api.voidCalls.isEmpty())
    }
}
