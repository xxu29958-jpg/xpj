package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.test.runTest
import java.io.IOException
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.*

class MonthlyArrangementDispatcherTest {
    private val adapters = OutboxAdapterGraph()
    private val receipt = MonthlyArrangementDto("owner", "2026-09", "JPY", 1200, 300, 1, "2026-09-27T00:00:00Z")
    private fun row() = OutboxRow(id = 1, serverUrl = "https://example.test", ledgerId = "owner",
        type = PendingMutationType.SaveMonthlyArrangement, targetId = "monthly_arrangement:2026-09",
        payloadJson = adapters.arrangementSaveAdapter.toJson(MonthlyArrangementPayload(1, "2026-09", MonthlyArrangementSaveRequest("JPY", 1200, 300))),
        expectedRowVersion = 0, status = PendingMutationStatus.InFlight, retryCount = 0, lastError = null,
        createdAt = "2026-09-27T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "original-arrangement")
    @Test fun ackLossContinuesOriginalKeyCurrencyMinorUnitsAndOcc() = runTest {
        val calls = mutableListOf<Pair<MonthlyArrangementSaveRequest, String>>()
        var lose = true
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun saveMonthlyArrangement(month: String, request: MonthlyArrangementSaveRequest, idempotencyKey: String): MonthlyArrangementDto {
                calls += request to idempotencyKey
                if (lose) throw IOException("ACK lost after commit")
                return receipt
            }
        }
        val dispatcher = SaveMonthlyArrangementDispatcher({ api }, adapters.arrangementSaveAdapter, adapters.arrangementReceiptAdapter)
        assertIs<DispatchResult.RetryableFailure>(dispatcher.dispatch(row()))
        lose = false
        val success = assertIs<DispatchResult.Success>(dispatcher.dispatch(row()))
        assertEquals(calls.first(), calls.last())
        assertEquals(1200L, calls.last().first.savingsTargetCents)
        assertNull(calls.last().first.expectedRowVersion)
        assertNull(success.newRowVersion, "An ACK must not silently rebase another original")
        assertEquals(receipt, adapters.arrangementReceiptAdapter.fromJson(assertNotNull(success.receiptJson)))
    }
    @Test fun wrongReceiptOrMissingRouteNeverProvesSaved() = runTest {
        for (wrong in listOf(receipt.copy(homeCurrencyCode = "CNY"), receipt.copy(month = "2026-08"),
            receipt.copy(rowVersion = 2), receipt.copy(savingsTargetCents = 12), receipt.copy(ledgerId = "other"))) {
            val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
                override suspend fun saveMonthlyArrangement(month: String, request: MonthlyArrangementSaveRequest, idempotencyKey: String) = wrong
            }
            assertIs<DispatchResult.Failure>(SaveMonthlyArrangementDispatcher({ api }, adapters.arrangementSaveAdapter,
                adapters.arrangementReceiptAdapter).dispatch(row()))
        }
    }
    @Test fun occConflictRemainsAnOriginalRequiringReview() = runTest {
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun saveMonthlyArrangement(month: String, request: MonthlyArrangementSaveRequest, idempotencyKey: String): MonthlyArrangementDto {
                throw HttpException(Response.error<MonthlyArrangementDto>(409,
                    """{"error":"state_conflict","message":"另一端已修改安排。"}""".toResponseBody()))
            }
        }
        assertIs<DispatchResult.Conflict>(SaveMonthlyArrangementDispatcher({ api }, adapters.arrangementSaveAdapter,
            adapters.arrangementReceiptAdapter).dispatch(row()))
    }
    @Test fun originalCurrencyPrecisionCannotBeReinterpretedAsNewHome() {
        assertEquals(1200L, MonthlyArrangementDraft("JPY", "1200", "300", null).request().savingsTargetCents)
        assertEquals(120000L, MonthlyArrangementDraft("CNY", "1200", "300", null).request().savingsTargetCents)
        assertFails { MonthlyArrangementDraft("JPY", "1200.5", "300", null).request() }
        assertFails { MonthlyArrangementDraft("XXX", "1200", "300", null).request() }
        assertFails { MonthlyArrangementDraft("CNY", "1.001", "300", null).request() }
        assertFails { MonthlyArrangementDraft("JPY", "9000000000001", "0", null).request() }
        assertEquals(com.ticketbox.domain.model.MONEY_MINOR_MAX, MonthlyArrangementDraft("JPY", "9000000000000", "0", null).request().savingsTargetCents)
    }
}
