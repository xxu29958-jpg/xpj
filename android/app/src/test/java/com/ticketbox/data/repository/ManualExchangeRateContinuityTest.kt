package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateListDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ManualExchangeRateContinuityTest {
    @Test fun everyReceiptFieldMustMatchTheOriginalAnd404NeverCompletes() = runTest {
        val f = ManualRateFixture()
        val id = f.repository.enqueueRate(f.binding, "2026-09", f.request, null).getOrThrow()
        val pending = f.pending(id)
        val intent = requireNotNull(pending.intent)
        val mismatches = listOf(f.latest.copy(publicId = ""), f.latest.copy(currencyCode = "USD"),
            f.latest.copy(homeCurrencyCode = "USD"), f.latest.copy(rateDate = "2026-09-02"),
            f.latest.copy(rateToHome = "0.06"), f.latest.copy(source = "automatic"), f.latest.copy(rowVersion = 2))
        assertTrue(mismatches.none { intent.accepts(pending.row, it) })
        val missing = ManualExchangeRateDispatcher({ throw HttpException(Response.error<Unit>(404, "{}".toResponseBody())) },
            f.adapters.manualRateAdapter, f.adapters.manualRateReceiptAdapter)
        assertTrue(missing.dispatch(pending.row) is DispatchResult.Failure)
        assertFalse(f.pending(id).isConfirmed)
    }

    @Test fun savedRateIntentSurvivesLostAckAndReplaysOriginalReceiptWithoutReplacingCurrentRate() = runTest {
        val f = ManualRateFixture()
        val id = f.repository.enqueueRate(f.binding, "2026-09", f.request, null).getOrThrow()
        val original = f.dao.rows.getValue(id)
        assertTrue(f.keys.isEmpty())
        assertEquals(1, f.engine.drainOnce().failures)
        assertEquals(0, f.adviceInvalidations)
        f.latest = f.latest.copy(rateToHome = "0.06000000", rowVersion = 3)
        f.repository.recoverRate(f.binding, f.pending(id), false).getOrThrow()
        f.loseAck = false
        assertEquals(1, f.engine.drainOnce().done)
        assertEquals(1, f.adviceInvalidations)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.keys)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals("0.05", f.pending(id).receipt?.rateToHome)
        assertEquals("0.06000000", f.repository.exchangeRates(f.binding).getOrThrow().single().rateToHome)
    }

    @Test fun rejectedOrUnverifiedRateKeepsOriginalAndRequiresReview() = runTest {
        val f = ManualRateFixture()
        val id = f.repository.enqueueRate(f.binding, "2026-09", f.request, null).getOrThrow()
        f.loseAck = false
        f.latest = f.latest.copy(homeCurrencyCode = "USD")
        assertEquals(1, f.engine.drainOnce().failures)
        assertEquals(0, f.adviceInvalidations)
        assertFalse(f.pending(id).isConfirmed)
        assertFalse(f.pending(id).canRetry)
        assertTrue(f.repository.enqueueRate(f.binding, "2026-09", f.request, null).isFailure)
        val pending = f.pending(id)
        assertTrue(f.dispatcher.dispatch(pending.row.copy(payloadJson = "{}")) is DispatchResult.Failure)
        assertEquals(1, f.keys.size)
    }

    @Test fun conflictDoesNotChangeOriginalVersionAndNewCorrectionRequiresExplicitStopAndNewIntent() = runTest {
        val f = ManualRateFixture()
        val id = f.repository.enqueueRate(f.binding, "2026-09", f.request, null).getOrThrow()
        val original = f.dao.rows.getValue(id)
        f.outbox.markConflict(id, "state_conflict")
        assertFalse(f.pending(id).canRetry)
        assertTrue(f.repository.recoverRate(f.binding, f.pending(id), false).isFailure)
        f.repository.recoverRate(f.binding, f.pending(id), true).getOrThrow()
        val next = f.repository.enqueueRate(f.binding, "2026-09",
            f.request.copy(expectedRowVersion = 1), f.latest.publicId).getOrThrow()
        assertTrue(original.idempotencyKey != f.dao.rows.getValue(next).idempotencyKey)
        assertEquals(1L, f.pending(next).row.expectedRowVersion)
    }

    @Test fun changedBindingCannotSaveOrStopTheOriginalRate() = runTest {
        val f = ManualRateFixture()
        val id = f.repository.enqueueRate(f.binding, "2026-09", f.request, null).getOrThrow()
        f.outbox.markFailed(id, "client_upgrade_required")
        val pending = f.pending(id)
        f.session.switchLedgerForFixture("other", "Other")
        assertTrue(f.repository.enqueueRate(f.binding, "2026-09", f.request, null).isFailure)
        assertTrue(f.repository.recoverRate(f.binding, pending, true).isFailure)
        assertEquals(null, f.repository.describeRate(pending.row))
        assertTrue(f.dao.rows.containsKey(id))
        assertTrue(f.keys.isEmpty())
        assertEquals(0, f.engine.drainOnce().attempted)
        assertEquals(0, f.adviceInvalidations)
    }
}

internal class ManualRateFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-rate-session") }
    val adapters = OutboxAdapterGraph()
    val dao = FakePendingMutationDao()
    val outbox = testOutboxRepository(dao, bindingProvider = { session.sessionStore.currentSession().toOutboxBinding() })
    val request = ExchangeRateRequestDto("JPY", "CNY", "2026-09-01", "0.05", "manual", 0)
    var latest = ExchangeRateDto("manual-rate", "JPY", "CNY", "2026-09-01", "0.05", "manual",
        "2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z", 1)
    var loseAck = true
    val keys = mutableListOf<String>()
    val receipts = mutableMapOf<String, ExchangeRateDto>()
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun exchangeRates(currencyCode: String?, homeCurrencyCode: String?, rateDate: String?, limit: Int) =
            ExchangeRateListDto(listOf(latest))
        override suspend fun saveExchangeRate(currencyCode: String, rateDate: String,
            request: ExchangeRateRequestDto, idempotencyKey: String): ExchangeRateDto {
            assertEquals(request.currencyCode, currencyCode)
            assertEquals(request.rateDate, rateDate)
            keys += idempotencyKey
            val receipt = receipts.getOrPut(idempotencyKey) { latest }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return receipt
        }
    }
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val repository = ManualExchangeRateRepository(provider, outbox, adapters.manualRateAdapter, adapters.manualRateReceiptAdapter)
    val dispatcher = ManualExchangeRateDispatcher({ api }, adapters.manualRateAdapter, adapters.manualRateReceiptAdapter)
    var adviceInvalidations = 0
    val engine = OutboxDrainEngine(outbox, listOf(dispatcher), maxAttempts = 1).apply {
        onAdviceInputReplaySucceeded = { adviceInvalidations += 1 }
    }
    suspend fun pending(id: Long) = repository.observeRates(binding).first().single { it.row.id == id }
}
