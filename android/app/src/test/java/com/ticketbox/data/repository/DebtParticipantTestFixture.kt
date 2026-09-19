package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.security.LocalSessionIdentity

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
