package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.click
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtRepaymentHistoryViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class DebtAdjustmentRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = DebtAdjustmentConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val detail = mutableStateOf<DebtDetailViewModel?>(null)
    private lateinit var proposals: MemberRepaymentProposalViewModel
    private lateinit var history: DebtRepaymentHistoryViewModel

    @After
    fun close() { stopModels(); fixture.close() }

    @Test
    fun actualSaveAndRetryKeepTheOriginalAdjustmentAcrossRoomReopenAndFailedDetailRead() {
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt != null }
        compose.onNodeWithText("调整本金").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(2)
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("30.00")
        compose.onAllNodes(hasSetTextAction())[1].performTextReplacement("补记原借款")
        compose.onNodeWithText("保存").performScrollTo().assertIsDisplayed().performTouchInput { click() }
        compose.waitUntil(10_000) { fixture.stored().size == 1 && detail.value?.state?.value?.activeAction == null }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals(50_000L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals("2", original["expectedRowVersion"])
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        assertEquals(1, fixture.network.results.size)

        stopModels()
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { detail.value?.state?.value?.error != null &&
            detail.value?.state?.value?.pendingAdjustments?.size == 1 }
        for (key in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
            assertEquals(original[key], fixture.stored().single()[key])
        }
        compose.onNodeWithText("补记原借款").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原调整").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        fixture.network.loseResponse = false
        fixture.network.failReads = false
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 3L }
        assertEquals(53_000L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().second)
        assertEquals(1, fixture.network.results.size)
        assertEquals(emptyList<PendingDebtAdjustment>(), detail.value?.state?.value?.pendingAdjustments)
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            proposals = MemberRepaymentProposalViewModel(graph.debtRepository.proposals)
            history = DebtRepaymentHistoryViewModel(graph.debtRepository.repayments)
            detail.value = DebtDetailViewModel(graph.debtRepository, graph.debtAdjustmentRepository)
                .also { it.loadDebt(fixture.network.current.publicId) }
        }
    }

    private fun stopModels() = compose.runOnIdle {
        detail.value?.viewModelScope?.cancel()
        if (::proposals.isInitialized) proposals.viewModelScope.cancel()
        if (::history.isInitialized) history.viewModelScope.cancel()
    }
}
