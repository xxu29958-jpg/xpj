package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class IncomePlanRepositoryBindingTest {
    @Test
    fun switchedLedgerCannotSubmitAnEditFromThePreviousBinding() = runTest {
        val fixture = IncomeEditFixture()
        val originalBinding = fixture.binding()
        fixture.session.switchLedgerForFixture("other", "另一本账")

        val result = fixture.repository.update(
            originalBinding,
            "income-1",
            IncomePlanPatch(expectedRowVersion = 3, amountCents = 210_000),
        )

        assertTrue(result.exceptionOrNull() is RepositoryException)
        assertTrue(fixture.api.requests.isEmpty(), "Old draft must not issue a command in the new ledger")
    }

    @Test
    fun sameBindingSubmitsOriginalOccAndReturnsCanonicalPlan() = runTest {
        val fixture = IncomeEditFixture()

        val saved = fixture.repository.update(
            fixture.binding(),
            "income-1",
            IncomePlanPatch(expectedRowVersion = 3, amountCents = 210_000),
        ).getOrThrow()

        val request = fixture.api.requests.single()
        assertEquals("income-1", request.first)
        assertEquals(3L, request.second.expectedRowVersion)
        assertEquals(210_000L, request.second.amountCents)
        assertNotNull(fixture.api.idempotencyKey)
        assertEquals("income-1", saved.publicId)
        assertEquals(210_000L, saved.amountCents)
        assertEquals(4L, saved.rowVersion)
    }
}

private class IncomeEditFixture {
    val session = TestSessionFixture().apply { saveToken("test-session") }
    val api = IncomeEditApi()
    private val provider = testApiServiceProvider(
        object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        },
        session,
    )
    val repository = IncomePlanRepository(provider)

    fun binding(): LogicalSessionBinding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
}

private class IncomeEditApi : ApiService by FakeApiService(mutableListOf(), 0) {
    val requests = mutableListOf<Pair<String, IncomePlanUpdateRequestDto>>()
    var idempotencyKey: String? = null

    override suspend fun updateIncomePlan(
        publicId: String,
        request: IncomePlanUpdateRequestDto,
        idempotencyKey: String?,
    ): IncomePlanDto {
        requests += publicId to request
        this.idempotencyKey = idempotencyKey
        return IncomePlanDto(
            publicId = "income-1", label = "兼职收入", sourceType = "salary",
            frequency = "monthly", incomeMonth = null, amountCents = 210_000, payDay = 10,
            status = "active", createdAt = "2026-09-01T00:00:00Z",
            updatedAt = "2026-09-03T00:00:00Z", rowVersion = 4, archivedAt = null,
        )
    }
}
