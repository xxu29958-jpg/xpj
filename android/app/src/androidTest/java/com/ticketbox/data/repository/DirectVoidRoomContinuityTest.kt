package com.ticketbox.data.repository

import androidx.lifecycle.viewModelScope
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentVoidCreateRequestDto
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.viewmodel.DebtDetailViewModel
import java.io.IOException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** Real detail producer and disk Room; the remote commits before losing the response. */
class DirectVoidRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val remote = DirectVoidRoomProbe()
    private val fixture = DebtAdjustmentConnectedFixture(
        InstrumentationRegistry.getInstrumentation().targetContext, remote.service,
    )
    private var detail: DebtDetailViewModel? = null

    @After fun close() { stopDetail(); fixture.close() }

    @Test fun committedDebtVoidLostAckSurvivesRoomReopenDespiteTerminalDebt() {
        assertOriginalSurvivesReopen(DebtAction.Void)
    }

    @Test fun committedRepaymentVoidLostAckSurvivesRoomReopenDespiteRestoredBalance() {
        assertOriginalSurvivesReopen(DebtAction.RepaymentVoid)
    }

    @Test fun debtVoidRetryAfterGraphReopenKeepsOriginalKeyBodyAndOcc() {
        assertOriginalReplay(DebtAction.Void)
    }

    @Test fun repaymentVoidRetryAfterGraphReopenKeepsOriginalReceiptTargetKeyBodyAndOcc() {
        assertOriginalReplay(DebtAction.RepaymentVoid)
    }

    private fun assertOriginalSurvivesReopen(action: DebtAction) {
        installDetail()
        compose.waitUntil(10_000) { detail?.state?.value?.canWriteActions == true }
        compose.runOnIdle {
            requireNotNull(detail).openAction(action, remote.payment.takeIf { action == DebtAction.RepaymentVoid })
            requireNotNull(detail).updateActionInput(reason = "  原记录重复  ")
            requireNotNull(detail).submit()
        }
        compose.waitUntil(10_000) { remote.calls.size == 1 && detail?.state?.value?.isSubmitting == false }
        assertEquals(1, remote.facts.size)
        assertEquals("原记录重复", remote.calls.single().reason)
        assertEquals(2L, remote.calls.single().expectedRowVersion)
        assertEquals(if (action == DebtAction.Void) "voided" else "open", remote.current.status)
        assertEquals(if (action == DebtAction.Void) 0L else 50_000L, remote.current.remainingAmountCents)
        stopDetail()
        installDetail()
        compose.waitUntil(10_000) { detail?.state?.value?.writeSnapshotLoaded == true &&
            detail?.state?.value?.debt?.rowVersion == 3L }

        // A terminal debt/restored balance is not this submission's acknowledgement.
        val pending = requireNotNull(detail).state.value.pendingWrites
        assertEquals("The original committed-but-unacknowledged void must remain recoverable", 1, pending.size)
        assertTrue(pending.single().isUnresolved)
        assertFalse(requireNotNull(detail).state.value.canWriteActions)
        val original = fixture.stored().single()
        assertEquals(remote.calls.single().key, original["idempotencyKey"])
        assertEquals("2", original["expectedRowVersion"])
        assertTrue(requireNotNull(original["payload"]).contains("原记录重复"))
        if (action == DebtAction.RepaymentVoid) {
            assertTrue(requireNotNull(original["payload"]).contains(remote.payment.publicId))
        }
        compose.runOnIdle { requireNotNull(detail).recoverDebtWrite(pending.single(), drop = false) }
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        val retry = fixture.stored().single()
        for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl", "createdAt")) {
            assertEquals(original[field], retry[field])
        }
        assertEquals(1, remote.facts.size)
    }

    private fun assertOriginalReplay(action: DebtAction) = runBlocking {
        val firstGraph = fixture.reopen()
        val original = remote.current
        assertTrue(submit(firstGraph.debtRepository, original, action).isFailure)
        assertEquals(1, remote.facts.size)
        remote.loseResponse = false
        val reopenedGraph = fixture.reopen()
        val replay = submit(reopenedGraph.debtRepository, original, action)
        assertEquals("A refused replacement must not append or rewrite the original fact", 1, remote.facts.size)
        assertEquals(remote.facts.values.single().second, remote.current)
        assertEquals(remote.calls.first().copy(key = ""), remote.calls.last().copy(key = ""))
        assertEquals("Recovery must reuse the original key rather than write another correction",
            remote.calls.first().key, remote.calls.last().key)
        assertTrue(replay.isSuccess)
        assertEquals(1, remote.facts.size)
        assertEquals(3L, replay.getOrThrow().rowVersion)
    }

    private suspend fun submit(repository: DebtRepository, original: DebtDto, action: DebtAction) = when (action) {
        DebtAction.Void -> repository.voidDebt(original.publicId, original.rowVersion, "  原记录重复  ")
        DebtAction.RepaymentVoid -> repository.voidRepayment(original.publicId, remote.payment.publicId,
            original.rowVersion, "  原记录重复  ")
        else -> error("Only the two direct void owners are in scope")
    }

    private fun installDetail() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            detail = DebtDetailViewModel(graph.debtRepository, graph.debtWriteRepository)
                .also { it.loadDebt(remote.current.publicId) }
        }
    }

    private fun stopDetail() = compose.runOnIdle { detail?.viewModelScope?.cancel() }
}

private data class OriginalVoidRoomCall(
    val debtPublicId: String, val repaymentPublicId: String?, val reason: String,
    val expectedRowVersion: Long, val key: String,
)

/** Mirrors claim-before-OCC and immutable original result; it is not a second server owner. */
private class DirectVoidRoomProbe {
    private val baseline = DebtAdjustmentConnectedNetwork()
    var current = baseline.current.copy(remainingAmountCents = 40_000, paidAmountCents = 10_000)
    val payment = DebtRepayment("repayment-original", 10_000, current.createdAt, current.createdAt, "active")
    var loseResponse = true
    val calls = mutableListOf<OriginalVoidRoomCall>()
    val facts = mutableMapOf<String, Pair<OriginalVoidRoomCall, DebtDto>>()
    val service = object : ApiService by baseline.service {
        override suspend fun debt(publicId: String): DebtDto {
            check(publicId == current.publicId)
            return current
        }

        override suspend fun voidDebt(publicId: String, request: DebtVoidCreateRequestDto,
            idempotencyKey: String?): DebtDto = commit(OriginalVoidRoomCall(publicId, null, request.reason,
            request.expectedRowVersion, requireNotNull(idempotencyKey)))

        override suspend fun voidDebtRepayment(publicId: String, request: RepaymentVoidCreateRequestDto,
            idempotencyKey: String?): DebtDto = commit(OriginalVoidRoomCall(publicId, request.repaymentPublicId,
            request.reason, request.expectedRowVersion, requireNotNull(idempotencyKey)))
    }

    private fun commit(call: OriginalVoidRoomCall): DebtDto {
        calls += call
        check(call.debtPublicId == current.publicId)
        facts[call.key]?.let { (original, receipt) ->
            check(original == call)
            return receipt
        }
        if (call.expectedRowVersion != current.rowVersion) {
            throw HttpException(Response.error<DebtDto>(409,
                """{"error":"state_conflict","message":"原记录已变化"}""".toResponseBody("application/json".toMediaType())))
        }
        check(call.repaymentPublicId == null || call.repaymentPublicId == payment.publicId)
        current = if (call.repaymentPublicId == null) {
            current.copy(status = "voided", remainingAmountCents = 0, rowVersion = current.rowVersion + 1)
        } else {
            current.copy(status = "open", remainingAmountCents = 50_000, paidAmountCents = 0,
                rowVersion = current.rowVersion + 1)
        }
        facts[call.key] = call to current
        if (loseResponse) throw IOException("Synthetic response loss after the original void committed")
        return current
    }
}
