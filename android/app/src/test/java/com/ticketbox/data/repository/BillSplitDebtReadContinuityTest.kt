package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.domain.model.DebtListLens
import java.net.ConnectException
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BillSplitDebtReadContinuityTest {
    @Test fun acceptingIntoAnotherLedgerCannotReuseThatLedgersEarlierBindingAfterSelection() = runTest {
        for (loseAck in listOf(false, true)) {
            val api = InvitationDebtApi().apply { this.loseAck = loseAck }
            val fixture = GoalReadFixture { api }
            suspend fun select(ledgerId: String) {
                val current = requireNotNull(fixture.session.sessionStore.currentSession()).identity
                fixture.coordinator.applyTransition(LedgerSessionTransition(LocalSessionChange.SelectLedger,
                    LedgerSessionIdentity(current.accountPublicId, current.devicePublicId, current.accountName,
                        ledgerId, ledgerId, current.deviceName, current.role, current.boundAt)))
            }
            fun reader() = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            select("target")
            val originalTarget = fixture.binding
            assertTrue(reader().list(originalTarget, DebtListLens.Ledger).getOrThrow().value.debts.isEmpty())
            select("owner")
            val accepted = fixture.stats.acceptBillSplitInvitation(fixture.binding, "split-jpy", "target")
            assertEquals(!loseAck, accepted.isSuccess)
            assertEquals(BillSplitAcceptRequestDto("target"), api.request)
            select("target")
            assertTrue(originalTarget.bindingRevision != fixture.binding.bindingRevision)
            api.offline = true
            assertTrue(reader().list(fixture.binding, DebtListLens.Ledger).isFailure,
                "A real new target selection cannot present its retired empty list, including after ACK loss")
            api.offline = false
            val recovered = reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow()
            assertEquals("received-debt", recovered.value.debts.single().publicId)
            assertEquals("target", recovered.value.debts.single().ledgerId)
            assertEquals("JPY", recovered.value.debts.single().homeCurrencyCode)
            assertEquals(1200L, recovered.value.debts.single().originalAmountMinor)
            api.offline = true
            assertEquals(recovered.copy(fromCache = true), reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow())
            assertEquals(1, api.acceptCalls)
        }
    }

    @Test fun acceptedInvitationCannotLeaveAnOldEmptyDebtListReadableAfterReopening() = runTest {
        val api = InvitationDebtApi()
        val fixture = GoalReadFixture { api }
        fun reader() = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val before = reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow()
        assertTrue(before.value.debts.isEmpty())
        val accepted = fixture.stats.acceptBillSplitInvitation(fixture.binding, "split-jpy", "owner").getOrThrow()
        assertEquals("accepted", accepted.status)
        assertEquals(BillSplitAcceptRequestDto("owner"), api.request)
        api.offline = true
        assertTrue(reader().list(fixture.binding, DebtListLens.Ledger).isFailure,
            "An accepted invitation creates a debt, so the old empty list cannot be offered offline")
        api.offline = false
        val refreshed = reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow()
        assertFalse(refreshed.fromCache)
        assertEquals("received-debt", refreshed.value.debts.single().publicId)
        assertEquals("JPY", refreshed.value.debts.single().homeCurrencyCode)
        assertEquals(1200L, refreshed.value.debts.single().originalAmountMinor)
        api.offline = true
        assertEquals(refreshed.copy(fromCache = true), reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow())
        assertEquals(1, api.acceptCalls)
    }

    @Test fun rejectedInvitationPreservesOriginalDebtReadAndDoesNotInventAcceptedFacts() = runTest {
        val api = InvitationDebtApi().apply { reject = true }
        val fixture = GoalReadFixture { api }
        fun reader() = DebtQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
        val original = reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow()
        val rejected = fixture.stats.acceptBillSplitInvitation(fixture.binding, "split-jpy", "owner")
        assertEquals(409, (rejected.exceptionOrNull() as RepositoryException).httpStatusCode)
        api.offline = true
        assertEquals(original.copy(fromCache = true), reader().list(fixture.binding, DebtListLens.Ledger).getOrThrow())
        assertFalse(api.accepted)
        assertEquals(1, api.acceptCalls)
    }
}

private class InvitationDebtApi : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
    var offline = false
    var reject = false
    var accepted = false
    var loseAck = false
    var acceptCalls = 0
    var request: BillSplitAcceptRequestDto? = null
    override suspend fun debts(lens: String?): DebtListResponseDto {
        if (offline) throw ConnectException("offline after invitation result")
        return DebtListResponseDto(if (accepted) listOf(DebtDto(publicId = "received-debt", ledgerId = request?.targetLedgerId,
            direction = "i_owe", counterpartyType = "member", counterpartyLabel = "原拆账发起人",
            principalAmountCents = 1200, remainingAmountCents = 1200, paidAmountCents = 0, status = "open",
            sourceType = "bill_split", homeCurrencyCode = "JPY", originalCurrencyCode = "JPY", originalAmountMinor = 1200,
            createdAt = "2026-09-27T01:00:00Z", updatedAt = "2026-09-27T01:00:00Z", rowVersion = 1)) else emptyList(), "JPY")
    }
    override suspend fun acceptBillSplitInvitation(publicId: String, request: BillSplitAcceptRequestDto): com.ticketbox.data.remote.dto.BillSplitInboxDto {
        this.request = request
        acceptCalls++
        if (reject) throw HttpException(Response.error<Any>(409, """{"error":"bill_split_not_pending"}""".toResponseBody()))
        accepted = true
        if (loseAck) throw ConnectException("accepted invitation ACK lost")
        return FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).acceptBillSplitInvitation(publicId, request)
            .copy(publicId = publicId, status = "accepted", amountCents = 1200, homeCurrencyCode = "JPY",
                acceptedAt = "2026-09-27T01:00:00Z")
    }
}
