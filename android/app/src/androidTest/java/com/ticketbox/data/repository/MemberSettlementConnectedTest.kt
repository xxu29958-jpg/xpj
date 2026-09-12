package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.ViewModel
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
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

class MemberSettlementConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val network = MemberSettlementConnectedNetwork()
    private val fixture = DebtAdjustmentConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext, network.service)
    private val detail = mutableStateOf<DebtDetailViewModel?>(null)
    private lateinit var proposals: MemberRepaymentProposalViewModel
    private lateinit var history: DebtRepaymentHistoryViewModel

    @After fun close() { stopModels(); fixture.close() }

    @Test
    fun partialConfirmationRetriesTheOriginalThenReachesSummaryHistoryAndReentry() {
        val graph = fixture.reopen()
        val binding = requireNotNull(graph.debtRepository.proposals.currentAccess()).binding
        runBlocking { graph.debtWriteRepository.save(binding, fixture.network.current.toDomain(), 100, "原离线意图").getOrThrow() }
        val retained = fixture.stored()
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { proposals.state.value.pendingProposal != null }
        compose.onNodeWithText("收到啦，谢谢～").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("450")
        compose.onNodeWithText("保存").performScrollTo().performTouchInput { click() }
        compose.waitUntil(10_000) { network.confirms.size == 1 && !proposals.state.value.isSubmitting }
        assertEquals("450", proposals.state.value.amountInput)
        assertNull(proposals.state.value.flashMessage)
        compose.onNodeWithText("保存").performScrollTo().performTouchInput { click() }
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 2L && history.state.value.total == 1 }
        assertEquals(2, network.confirms.size)
        assertEquals(network.confirms.first(), network.confirms.last())
        assertEquals(1, network.accepted.size)
        assertEquals(450L, history.state.value.items.single().amountCents)
        compose.onNodeWithText("¥750", substring = true).performScrollTo().assertIsDisplayed()
        assertEquals(retained, fixture.stored())

        stopModels()
        network.failReads = false
        installModels()
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 2L && history.state.value.total == 1 }
        assertEquals(2, network.confirms.size)
        assertEquals(retained, fixture.stored())
        compose.onNodeWithText("算了，不用还了").performScrollTo().performClick()
        compose.onNodeWithText("嗯，这份我请").performClick()
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.isForgiven == true }
        assertEquals(0L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals(450L, detail.value?.state?.value?.debt?.paidAmountCents)
        assertEquals(retained, fixture.stored())
    }

    @Test
    fun failedProposalReadOffersRetryBeforeClaimingEmptyOrAllowingForgiveness() {
        network.failProposalReads = true
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { proposals.state.value.error != null }
        compose.onNodeWithText("算了，不用还了").assertDoesNotExist()
        compose.onNodeWithText("还没有新消息", substring = true).assertDoesNotExist()
        network.failProposalReads = false
        compose.onNodeWithText("重试").performScrollTo().performClick()
        compose.waitUntil(10_000) { proposals.state.value.pendingProposal != null }
        compose.onNodeWithText("收到啦，谢谢～").performScrollTo().assertIsDisplayed()
        assertEquals(0, network.accepted.size)
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            proposals = MemberRepaymentProposalViewModel(graph.debtRepository.proposals)
            history = DebtRepaymentHistoryViewModel(graph.debtRepository.repayments)
            detail.value = DebtDetailViewModel(graph.debtRepository, graph.debtWriteRepository).also { it.loadDebt(network.current.publicId) }
        }
    }

    private fun stopModels() {
        compose.runOnIdle {
            if (detail.value == null) return@runOnIdle
            listOf<ViewModel>(requireNotNull(detail.value), proposals, history).forEach { it.viewModelScope.cancel() }
            detail.value = null
        }
    }
}
