package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtActivityListDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DebtActivityRepositoryTest {
    @Test
    fun activityPreservesKindsPartialConfirmationOriginalCurrencyAndVoidWithoutFolding() = runTest {
        val api = ActivityApi()
        val repository = repaymentRepository(api)
        val task = DebtTask(requireNotNull(repository.proposals.currentAccess()).binding, "debt-1")
        val result = repository.activity.listActivity(task, 1, "repayment-1").getOrThrow()
        assertEquals(listOf(Triple<String, Int, String?>("debt-1", 1, "repayment-1")), api.requests)
        assertEquals(3, result.page)
        assertEquals("JPY", result.homeCurrencyCode)
        assertEquals(151, result.total)
        assertEquals(listOf("proposal_created", "proposal_resolved", "repayment_void", "adjustment"), result.items.map { it.kind })
        assertEquals(4, result.items.map { it.key }.toSet().size)
        val proposal = requireNotNull(result.items[1].proposal)
        assertEquals(100L, proposal.proposedAmountCents)
        assertEquals(40L, proposal.confirmedAmountCents)
        assertEquals("repayment-1", proposal.committedRepaymentPublicId)
        assertEquals("older-proposal", proposal.supersedesProposalPublicId)
        val repayment = requireNotNull(result.items[2].repayment)
        assertFalse(repayment.isActive)
        assertEquals("重复记录", repayment.voidFact?.reason)
        assertEquals("2026-09-01T03:00:00Z", repayment.paidAt)
        assertEquals("USD", repayment.originalCurrencyCode)
        assertEquals(50L, repayment.originalAmountMinor)
        assertEquals("0.8", repayment.exchangeRateToCny)
        assertEquals("2026-09-01", repayment.exchangeRateDate)
        assertEquals("manual", repayment.exchangeRateSource)
        assertEquals(-5L, result.items[3].amountCents)
    }

    @Test
    fun anotherLogicalBindingCannotFetchOrReuseTheParticipantActivity() = runTest {
        val api = ActivityApi()
        val repository = repaymentRepository(api)
        val binding = requireNotNull(repository.proposals.currentAccess()).binding.copy(ledgerId = "other")
        assertTrue(repository.activity.listActivity(DebtTask(binding, "debt-1"), 1, null).isFailure)
        assertTrue(api.requests.isEmpty())
    }
}

private class ActivityApi : ApiService by FakeApiService(mutableListOf(), 0) {
    val requests = mutableListOf<Triple<String, Int, String?>>()
    override suspend fun debtActivity(publicId: String, page: Int, focusRepayment: String?): DebtActivityListDto {
        requests += Triple(publicId, page, focusRepayment)
        val proposal = """{"public_id":"proposal-1","debt_public_id":"debt-1","status":"partially_confirmed",
          "proposed_amount_cents":100,"confirmed_amount_cents":40,"home_currency_code":"JPY",
          "paid_at":"2026-09-01T03:00:00Z","created_at":"2026-09-02T03:00:00Z","expires_at":"2026-10-01T03:00:00Z",
          "resolved_at":"2026-09-03T03:00:00Z","supersedes_proposal_public_id":"older-proposal",
          "committed_repayment_public_id":"repayment-1"}"""
        val json = """{"debt_public_id":"debt-1","home_currency_code":"JPY","page":3,"page_size":50,"total":151,
          "items":[
           {"kind":"proposal_created","public_id":"proposal-1","recorded_at":"2026-09-02T03:00:00Z","actor_is_you":true,"proposal":$proposal},
           {"kind":"proposal_resolved","public_id":"proposal-1","recorded_at":"2026-09-03T03:00:00Z","actor_is_you":false,"proposal":$proposal},
           {"kind":"repayment_void","public_id":"void-1","recorded_at":"2026-09-04T03:00:00Z","actor_is_you":true,
            "repayment":{"public_id":"repayment-1","amount_cents":40,"paid_at":"2026-09-01T03:00:00Z",
            "created_at":"2026-09-03T03:00:00Z","status":"voided","original_currency_code":"USD","original_amount_minor":50,
            "exchange_rate_to_cny":"0.8","exchange_rate_date":"2026-09-01","exchange_rate_source":"manual",
            "void_fact":{"public_id":"void-1","reason":"重复记录","created_at":"2026-09-04T03:00:00Z"}}},
           {"kind":"adjustment","public_id":"adjustment-1","recorded_at":"2026-09-05T03:00:00Z","actor_is_you":true,"amount_cents":-5,"reason":"订正"}
          ]}"""
        return requireNotNull(Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(DebtActivityListDto::class.java).fromJson(json))
    }
}
