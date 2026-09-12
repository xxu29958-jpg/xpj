package com.ticketbox.data.repository

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.FakeDebtAdjustmentActions
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DirectRepaymentIntentTest {
    @Test fun retryingTheUnchangedOriginalFormAfterLostResponseKeepsItsCommand() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val api = RepaymentResponseLossProbe()
        val session = TestSessionFixture().apply { saveToken("synthetic-session") }
        val provider = testApiServiceProvider(object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        }, session)
        val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
        val adjustments = FakeDebtAdjustmentActions(MutableStateFlow(LedgerAccessContext(binding, true)))
        val model = DebtDetailViewModel(DebtRepository(provider), adjustments)
        try {
            model.loadDebt("d1")
            withContext(Dispatchers.Default) {
                withTimeout(5_000) { model.state.first { it.adjustmentSnapshotLoaded && !it.isLoading } }
            }
            assertTrue(model.state.value.canWriteActions)
            model.openAction(DebtAction.Repayment)
            model.updateActionInput(amount = "100")
            model.submit()
            withContext(Dispatchers.Default) { withTimeout(5_000) { model.state.first { !it.isSubmitting } } }
            assertEquals(1, api.facts.size)
            assertEquals(DebtAction.Repayment, model.state.value.activeAction)
            assertEquals("100", model.state.value.amountInput)
            assertNotNull(model.state.value.validationError)

            // The user continues this failed form; no new form, amount or intent.
            model.submit()
            withContext(Dispatchers.Default) { withTimeout(5_000) { model.state.first { !it.isSubmitting } } }

            assertEquals(2, api.calls.size)
            assertEquals(api.calls.first(), api.calls.last())
            assertEquals(1, api.facts.size)
            assertEquals(40_000L, model.state.value.debt?.remainingAmountCents)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }
}

private data class OriginalRepaymentCall(
    val target: String, val request: RepaymentCreateRequestDto, val key: String,
)

private class RepaymentResponseLossProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<OriginalRepaymentCall>()
    val facts = mutableMapOf<String, Pair<RepaymentCreateRequestDto, DebtDto>>()
    private var current = DebtDto(
        publicId = "d1", ledgerId = "owner", direction = "i_owe", counterpartyType = "external",
        counterpartyLabel = "Bank", principalAmountCents = 50_000L, remainingAmountCents = 50_000L,
        paidAmountCents = 0L, status = "open", sourceType = "manual", homeCurrencyCode = "CNY",
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-01T00:00:00Z", rowVersion = 1L,
    )

    override suspend fun debt(publicId: String): DebtDto = current

    override suspend fun recordDebtRepayment(
        publicId: String, request: RepaymentCreateRequestDto, idempotencyKey: String?,
    ): DebtDto {
        val key = requireNotNull(idempotencyKey)
        calls += OriginalRepaymentCall(publicId, request, key)
        facts[key]?.let { (original, receipt) ->
            check(request == original)
            return receipt
        }
        if (request.expectedRowVersion != current.rowVersion) {
            throw HttpException(Response.error<DebtDto>(409,
                """{"error":"state_conflict","message":"原版本已变化"}""".toResponseBody("application/json".toMediaType())))
        }
        current = current.copy(remainingAmountCents = current.remainingAmountCents - request.amountCents,
            paidAmountCents = current.paidAmountCents + request.amountCents, rowVersion = current.rowVersion + 1L)
        facts[key] = request to current
        throw IOException("Synthetic lost response after repayment commit")
    }
}
