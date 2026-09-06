package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BillSplitInviteRequestDto
import com.ticketbox.data.remote.dto.BillSplitSentDto
import com.ticketbox.data.remote.dto.ExpenseRepaymentDraftCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactWriteBindingTest {
    @Test
    fun queuedRepaymentCannotCaptureAnotherServersFact() = runTest {
        val fixture = FactWriteBindingFixture()
        val original = assertNotNull(fixture.repository.captureDeferredLedgerBinding())
        val release = CompletableDeferred<Unit>()
        val queued = async(start = CoroutineStart.UNDISPATCHED) {
            release.await()
            fixture.repository.createRepaymentDraftFromExpense(original, fixture.expense)
        }
        fixture.session.rebindToDifferentServerForFixture("https://other.test", "other-session")
        assertNotEquals(original, fixture.repository.captureDeferredLedgerBinding())
        release.complete(Unit)

        assertTrue(queued.await().isFailure)
        assertTrue(fixture.calls.isEmpty(), "No request may bind the original fact to the new server")
    }

    @Test
    fun queuedSplitCannotInviteFromAnotherServersFact() = runTest {
        val fixture = FactWriteBindingFixture()
        val original = assertNotNull(fixture.repository.captureDeferredLedgerBinding())
        val release = CompletableDeferred<Unit>()
        val queued = async(start = CoroutineStart.UNDISPATCHED) {
            release.await()
            fixture.repository.createBillSplitInvitation(original, fixture.expense.id, 22L, 400L)
        }
        fixture.session.rebindToDifferentServerForFixture("https://other.test", "other-session")
        assertNotEquals(original, fixture.repository.captureDeferredLedgerBinding())
        release.complete(Unit)

        assertTrue(queued.await().isFailure)
        assertTrue(fixture.calls.isEmpty(), "No invitation may use the new server with the old source identity")
    }

    @Test
    fun originalBindingStillSendsTheSelectedFactAndOcc() = runTest {
        val fixture = FactWriteBindingFixture()
        val original = assertNotNull(fixture.repository.captureDeferredLedgerBinding())

        val repayment = fixture.repository.createRepaymentDraftFromExpense(original, fixture.expense)
        val split = fixture.repository.createBillSplitInvitation(original, fixture.expense.id, 22L, 400L)

        assertTrue(repayment.isSuccess)
        assertTrue(split.isSuccess)
        assertEquals(listOf(
            "${original.serverUrl}:repayment:${fixture.expense.id}:${fixture.expense.rowVersion}",
            "${original.serverUrl}:split:${fixture.expense.id}:22:400",
        ), fixture.calls)
    }
}

private class FactWriteBindingFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    val expense = confirmedExpenseDtoFixture().toDomain()
    val calls = mutableListOf<String>()
    val repository = expenseRepositoryFixture(
        expenseDao = FakeExpenseDao(),
        binding = testServerSessionBinding(
            apiClient = object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api(baseUrl)
            },
            settingsStore = FakeTicketboxSettingsStore(), tokenStore = session,
        ),
        deviceNameProvider = { "Synthetic Android" },
    )

    private fun api(baseUrl: String): ApiService {
        val fallback = FakeApiService(mutableListOf(), 0)
        return object : ApiService by fallback {
            override suspend fun createRepaymentDraftFromExpense(
                id: String,
                request: ExpenseRepaymentDraftCreateRequestDto,
            ): RepaymentDraftDto {
                calls += "$baseUrl:repayment:$id:${request.expectedRowVersion}"
                return RepaymentDraftDto(
                    publicId = "draft-1", source = "expense", amountCents = 1_200L,
                    homeCurrencyCode = "CNY", capturedAt = "2026-09-07T00:00:00Z",
                    status = "pending", createdAt = "2026-09-07T00:00:00Z",
                )
            }

            override suspend fun createBillSplitInvitation(
                id: Long,
                request: BillSplitInviteRequestDto,
            ): BillSplitSentDto {
                calls += "$baseUrl:split:$id:${request.receiverAccountId}:${request.amountCents}"
                return fallback.createBillSplitInvitation(id, request).copy(senderExpenseId = id)
            }
        }
    }
}
