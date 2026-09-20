package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import retrofit2.http.GET
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class DebtActivityContractTest {
    @Test fun splitAgreementHistoryKeepsImmutableSharesCashAndForgivenessWithoutReplacingOtherEvents() {
        val event = com.ticketbox.data.remote.dto.DebtActivityDto(
            kind = "split_agreement_changed", publicId = "change", recordedAt = "2026-09-20T00:00:00Z",
            actorIsYou = false, splitChange = splitTestProposal().copy(status = "accepted"),
        )
        val dto = com.ticketbox.data.remote.dto.DebtActivityListDto("original", "CNY", listOf(event), 2, 50, 51)
        val page = dto.toDomain()
        val change = requireNotNull(page.items.single().splitChange)
        assertEquals(4000L, change.shareBeforeAmountCents)
        assertEquals(2000L, change.newShareAmountCents)
        assertEquals(-1000L, change.settlementNetAmountCents)
        assertEquals(1000L, change.originalForgivenAmountCents)
        assertEquals(3000L, change.originalPaidAmountCents)
        assertEquals("accepted", change.status)
        assertEquals(2, page.page)
        assertEquals(51, page.total)
        assertEquals(null, page.items.single().amountCents)
    }

    @Test
    fun existingDebtClientExposesCompleteActivityWithoutRemovingRepaymentCompatibility() {
        val activity = ApiService::class.java.methods.singleOrNull { it.name == "debtActivity" }
        assertNotNull(activity, "Debt details need the complete participant activity endpoint")
        assertEquals("api/debts/{publicId}/activity", activity.getAnnotation(GET::class.java)?.value)
        val legacy = ApiService::class.java.methods.single { it.name == "debtRepayments" }
        assertEquals("api/debts/{publicId}/repayments", legacy.getAnnotation(GET::class.java)?.value)
    }
}
