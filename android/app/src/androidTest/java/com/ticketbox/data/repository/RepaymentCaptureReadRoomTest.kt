package com.ticketbox.data.repository

import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** Real disk projection and graph; raw captures stay separate from Debt targets and original commands. */
class RepaymentCaptureReadRoomTest {
    private var offline = false
    private var refused = false
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext()) { delegate ->
        object : ApiService by delegate {
            override suspend fun repaymentDrafts(status: String?): RepaymentDraftListResponseDto {
                assertEquals("all", status)
                if (refused) throw HttpException(Response.error<Any>(403, """{"error":"permission_denied"}""".toResponseBody()))
                if (offline) throw ConnectException("isolated offline transport")
                return RepaymentDraftListResponseDto(listOf(capture("pending"), capture("confirmed"), capture("dismissed")))
            }
        }
    }

    @After fun close() = fixture.close()

    @Test fun reopenedDiskKeepsProcessedOriginalTargetsAndQueryCleanupPreservesUnsentInputs() = runBlocking {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.reportsRepository.dashboardAccess()).binding
        val read = graph.repaymentDraftRepository.readDrafts(binding).getOrThrow()
        graph.expenseRepository.submitCorrection(binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("原财务意图", note = "清理还款读取不得删除")).getOrThrow()
        val original = fixture.stored()
        assertTrue(original.isNotEmpty())
        offline = true
        val reopened = fixture.reopen()
        val retained = reopened.repaymentDraftRepository.readDrafts(binding).getOrThrow()
        assertTrue(retained.fromCache)
        assertEquals(read.fetchedAt, retained.fetchedAt)
        assertEquals(read.value, retained.value)
        assertEquals(listOf("pending", "confirmed", "dismissed"), retained.value.map { it.status })
        assertEquals("original-debt", retained.value[1].committedDebtPublicId)
        assertEquals("original-repayment", retained.value[1].committedRepaymentPublicId)
        assertTrue(retained.value.all { it.originalCurrencyCode == "CNY" && it.originalAmountMinor == 50000L && it.amountCents == null })
        reopened.expenseRepository.clearLocalCache()
        assertEquals(original, fixture.stored())
        assertTrue(reopened.repaymentDraftRepository.readDrafts(binding).isFailure)
    }

    @Test fun refusedOrReboundIdentityCannotReviveSavedCaptures() = runBlocking {
        var graph = fixture.reopen()
        graph.repaymentDraftRepository.readDrafts().getOrThrow()
        refused = true
        assertTrue(graph.repaymentDraftRepository.readDrafts().isFailure)
        refused = false
        offline = true
        graph = fixture.reopen()
        assertTrue(graph.repaymentDraftRepository.readDrafts().isFailure)
        offline = false
        graph.repaymentDraftRepository.readDrafts().getOrThrow()
        fixture.switchLedger()
        offline = true
        assertTrue(graph.repaymentDraftRepository.readDrafts().isFailure)
    }

    private fun capture(status: String) = RepaymentDraftDto(publicId = "original-$status", source = "alipay",
        amountCents = null, homeCurrencyCode = "JPY", merchantLabel = "原银行卡", capturedAt = "2026-09-01T08:00:00Z",
        status = status, createdAt = "2026-09-01T08:00:01Z", originalCurrencyCode = "CNY", originalAmountMinor = 50000,
        committedDebtPublicId = "original-debt".takeIf { status == "confirmed" },
        committedRepaymentPublicId = "original-repayment".takeIf { status == "confirmed" })
}
