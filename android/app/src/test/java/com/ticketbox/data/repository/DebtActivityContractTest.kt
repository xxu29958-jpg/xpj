package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import retrofit2.http.GET
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class DebtActivityContractTest {
    @Test fun dateOnlyPaymentSurvivesWireAndCacheWithoutAnInventedInstant() {
        val adapter = com.squareup.moshi.Moshi.Builder().add(com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory())
            .build().adapter(com.ticketbox.data.remote.dto.RepaymentFactDto::class.java)
        val body = """{"public_id":"original","amount_cents":300,"paid_at":null,
            "created_at":"2026-05-05T01:02:03Z","status":"active","accounting_time":{
            "precision":"date_only","user_local_date":"2026-04-30","accounting_date":"2026-05-01",
            "calendar_revision":3,"basis":"user_selected"}}"""
        val original = requireNotNull(adapter.fromJson(body))
        val reopened = requireNotNull(adapter.fromJson(adapter.toJson(original))).toDomain()
        assertEquals(null, reopened.paidAt)
        assertEquals("2026-04-30", reopened.accountingTime?.userLocalDate)
        assertEquals(3L, reopened.accountingTime?.calendarRevision)
        assertEquals(com.ticketbox.domain.model.UiText.res(
            com.ticketbox.R.string.accounting_time_date_with_ledger_day, "2026-04-30", "2026-05-01"),
            com.ticketbox.ui.components.accountingTimeDateText(reopened.accountingTime, reopened.paidAt))
    }

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
