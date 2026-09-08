package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import java.io.IOException
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class SaveMonthlyBudgetDispatcherTest {
    private val adapters = OutboxAdapterGraph()

    @Test
    fun lostResponseRetriesOriginalNullVersionCurrencyAndKey() = runTest {
        val stub = BudgetSaveStub(Result.failure(IOException("lost response")))
        val row = row(version = 0)
        val writer = dispatcher(stub)
        assertIs<DispatchResult.RetryableFailure>(writer.dispatch(row))
        stub.result = Result.success(receipt(version = 1))
        val success = assertIs<DispatchResult.Success>(writer.dispatch(row))
        assertEquals(listOf<String?>("original-budget-key", "original-budget-key"), stub.keys)
        assertEquals(2, stub.requests.size)
        assertEquals(stub.requests.first(), stub.requests.last())
        assertEquals("JPY", stub.requests.last().homeCurrencyCode)
        assertEquals(1200L, stub.requests.last().totalAmountCents)
        assertNull(stub.requests.last().expectedRowVersion)
        assertNotNull(success.receiptJson)
        assertNull(success.newRowVersion, "a saved budget must not silently rebase another intent")
    }

    @Test
    fun wrongMoneyOrTargetNeverSettlesTheOriginal() = runTest {
        val baseline = receipt()
        for (changed in listOf(baseline.copy(homeCurrencyCode = "CNY"), baseline.copy(totalAmountCents = 12),
            baseline.copy(ledgerId = "other"), baseline.copy(month = "2026-08"), baseline.copy(rowVersion = 1),
            baseline.copy(excludedCategories = listOf("医疗")))) {
            assertIs<DispatchResult.Failure>(dispatcher(BudgetSaveStub(Result.success(changed))).dispatch(row()))
        }
    }

    @Test
    fun protocolRefusalAndConflictRemainRecoverable() = runTest {
        val upgrade = HttpException(Response.error<BudgetMonthlyDto>(409,
            """{"error":"client_upgrade_required","message":"请升级客户端。"}""".toResponseBody()))
        val conflict = HttpException(Response.error<BudgetMonthlyDto>(409,
            """{"error":"state_conflict","message":"另一端已修改预算。"}""".toResponseBody()))
        assertIs<DispatchResult.Failure>(dispatcher(BudgetSaveStub(Result.failure(upgrade))).dispatch(row()))
        assertIs<DispatchResult.Conflict>(dispatcher(BudgetSaveStub(Result.failure(conflict))).dispatch(row()))
    }

    @Test
    fun unsupportedOrKeylessIntentDoesNotReachHttp() = runTest {
        val stub = BudgetSaveStub(Result.success(receipt()))
        val writer = dispatcher(stub)
        assertIs<DispatchResult.Failure>(writer.dispatch(row().copy(idempotencyKey = null)))
        assertIs<DispatchResult.Failure>(writer.dispatch(row().copy(payloadJson = "{}")))
        assertEquals(emptyList(), stub.requests)
    }

    private fun dispatcher(api: ApiService) = SaveMonthlyBudgetDispatcher({ api }, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter)

    private fun row(version: Long = 1) = OutboxRow(
        id = 1, serverUrl = "https://example.test", ledgerId = "owner", type = PendingMutationType.SaveMonthlyBudget,
        targetId = "monthly_budget:2026-09", payloadJson = adapters.budgetSaveAdapter.toJson(BudgetSavePayload(1,
            "2026-09", "UTC", BudgetMonthlyUpdateRequestDto("JPY", null, 1200))),
        expectedRowVersion = version, status = PendingMutationStatus.InFlight, retryCount = 0, lastError = null,
        createdAt = "2026-09-08T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "original-budget-key")

    private fun receipt(version: Long = 2) = BudgetMonthlyDto(
        ledgerId = "owner", month = "2026-09", configured = true, totalAmountCents = 1200,
        rolloverAmountCents = 0, fixedAmountCents = null, nonMonthlyAmountCents = 0, flexBudgetCents = null,
        spentAmountCents = null, excludedAmountCents = 0, remainingAmountCents = null, overspentAmountCents = null,
        excludedCategories = emptyList(), excludedBreakdown = emptyList(), categoryBudgets = emptyList(),
        updatedAt = null, rowVersion = version, homeCurrencyCode = "JPY")
}

private class BudgetSaveStub(var result: Result<BudgetMonthlyDto>) : ApiService by FakeApiService(mutableListOf(), 0) {
    val keys = mutableListOf<String?>()
    val requests = mutableListOf<BudgetMonthlyUpdateRequestDto>()
    override suspend fun updateMonthlyBudget(month: String, request: BudgetMonthlyUpdateRequestDto,
        timezone: String?, idempotencyKey: String?): BudgetMonthlyDto {
        keys += idempotencyKey
        requests += request
        return result.getOrThrow()
    }
}
