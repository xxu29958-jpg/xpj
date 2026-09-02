package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.RepaymentFactDto
import com.ticketbox.data.remote.dto.RepaymentFactListDto
import com.ticketbox.data.remote.dto.RepaymentVoidFactDto
import com.ticketbox.security.LocalSessionIdentity
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DebtRepaymentRepositoryTest {
    @Test
    fun historyKeepsOriginalPaymentAndItsVoidWithServerPagingAndCurrency() = runTest {
        val api = RepaymentHistoryApi()
        val repository = repaymentRepository(api).repayments

        val result = repository.listRepayments("debt-1", page = 2)

        assertTrue(result.isSuccess)
        val history = result.getOrThrow()
        assertEquals(listOf("debt-1" to 2), api.requests)
        assertEquals("JPY", history.homeCurrencyCode)
        assertEquals(2, history.page)
        assertEquals(51, history.total)
        assertEquals(50, history.pageSize)
        val payment = history.items.single()
        assertEquals("repayment-1", payment.publicId)
        assertEquals(1200L, payment.amountCents)
        assertEquals("voided", payment.status)
        assertEquals("重复记录", payment.voidFact?.reason)
        assertEquals("void-1", payment.voidFact?.publicId)
    }
}

private class RepaymentHistoryApi : ApiService by FakeApiService(mutableListOf(), 0) {
    val requests = mutableListOf<Pair<String, Int>>()

    override suspend fun debtRepayments(publicId: String, page: Int): RepaymentFactListDto {
        requests += publicId to page
        return RepaymentFactListDto(
            debtPublicId = publicId,
            homeCurrencyCode = "JPY",
            items = listOf(
                RepaymentFactDto(
                    publicId = "repayment-1", amountCents = 1200L,
                    paidAt = "2026-09-01T09:00:00Z", createdAt = "2026-09-01T09:01:00Z",
                    status = "voided",
                    voidFact = RepaymentVoidFactDto("void-1", "重复记录", "2026-09-02T09:00:00Z"),
                ),
            ),
            page = page, pageSize = 50, total = 51,
        )
    }
}

internal fun repaymentRepository(api: ApiService, role: String = "owner"): DebtRepository {
    val session = TestSessionFixture(
        identity = LocalSessionIdentity(
            accountName = "我", ledgerId = "owner", ledgerName = "我的小票夹",
            deviceName = "Pixel", role = role, boundAt = "2026-09-01T00:00:00Z",
        ),
    ).apply { saveToken("test-session") }
    val factory = object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }
    return DebtRepository(testApiServiceProvider(factory, session))
}
