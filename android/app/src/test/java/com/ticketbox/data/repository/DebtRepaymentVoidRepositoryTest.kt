package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.RepaymentVoidCreateRequestDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DebtRepaymentVoidRepositoryTest {
    @Test
    fun singlePaymentVoidCarriesParentVersionTargetReasonAndIdempotencyKey() = runTest {
        val api = VoidRepaymentApi()

        val result = repaymentRepository(api).voidRepayment("debt-1", "payment-7", 4, "  重复记录  ")

        assertTrue(result.isSuccess)
        val call = api.requests.single()
        assertEquals("debt-1", call.publicId)
        assertEquals("payment-7", call.body.repaymentPublicId)
        assertEquals(4L, call.body.expectedRowVersion)
        assertEquals("重复记录", call.body.reason)
        assertTrue(!call.key.isNullOrBlank())
        assertEquals(5L, result.getOrThrow().rowVersion)
        assertEquals(1200L, result.getOrThrow().remainingAmountCents)
        assertEquals("JPY", result.getOrThrow().homeCurrencyCode)
    }

    @Test
    fun viewerCannotSendTheNewCommand() = runTest {
        val api = VoidRepaymentApi()
        val result = repaymentRepository(api, role = "viewer")
            .voidRepayment("debt-1", "payment-7", 4, "重复记录")

        assertTrue(result.isFailure)
        assertTrue(api.requests.isEmpty())
    }
}

private data class RepaymentVoidCall(val publicId: String, val body: RepaymentVoidCreateRequestDto, val key: String?)

private class VoidRepaymentApi : ApiService by FakeApiService(mutableListOf(), 0) {
    val requests = mutableListOf<RepaymentVoidCall>()

    override suspend fun voidDebtRepayment(
        publicId: String,
        request: RepaymentVoidCreateRequestDto,
        idempotencyKey: String?,
    ): DebtDto {
        requests += RepaymentVoidCall(publicId, request, idempotencyKey)
        return DebtDto(
            publicId = publicId, ledgerId = "owner", direction = "i_owe", counterpartyType = "external",
            counterpartyLabel = "小林", principalAmountCents = 5000L,
            remainingAmountCents = 1200L, paidAmountCents = 3800L, status = "open", sourceType = "manual",
            homeCurrencyCode = "JPY", rowVersion = 5,
            createdAt = "2026-09-01T09:00:00Z", updatedAt = "2026-09-03T09:00:00Z",
        )
    }
}
