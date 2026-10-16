package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtActivityViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class MemberSettlementConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val network = MemberSettlementConnectedNetwork()
    private val fixture = DebtAdjustmentConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext, network.service)
    private val detail = mutableStateOf<DebtDetailViewModel?>(null)
    private lateinit var proposals: MemberRepaymentProposalViewModel
    private lateinit var history: DebtActivityViewModel
    private var proposalSavedState = SavedStateHandle()
    private val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper

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
            TicketboxTheme(skin = skin) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { proposals.state.value.pendingProposal != null }
        saveConsumerArtPreview("member-debt-primary", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("收到啦，谢谢～").assertIsDisplayed().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("450")
        compose.onNodeWithText("确认这笔到账").performTouchInput { click() }
        compose.waitUntil(10_000) { network.confirms.size == 1 && !proposals.state.value.isSubmitting }
        assertEquals("450", proposals.state.value.amountInput)
        assertNull(proposals.state.value.flashMessage)
        stopModels()
        proposalSavedState = SavedStateHandle(proposalSavedState.keys().associateWith { proposalSavedState.get<Any?>(it) })
        installModels()
        compose.waitUntil(10_000) { proposals.state.value.originalAttempt != null }
        assertNull(detail.value?.state?.value?.debt)
        assertEquals("450", proposals.state.value.amountInput)
        assertEquals("JPY", proposals.state.value.formCurrencyCode)
        assertEquals(network.current.counterpartyLabel, proposals.state.value.originalContext?.counterpartyLabel)
        compose.onNodeWithText("核实原提交结果").assertIsDisplayed()
        saveConsumerArtPreview("member-original-recovery", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("核实原提交结果").performClick()
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 2L && history.state.value.total == 3 }
        assertEquals(2, network.confirms.size)
        assertEquals(network.confirms.first(), network.confirms.last())
        assertEquals(MemberRepaymentProposalConfirmRequestDto(confirmedAmountCents = 450, expectedRowVersion = 1),
            network.confirms.first().first)
        assertEquals(450L, history.state.value.items.single { it.kind == "repayment" }.repayment?.amountCents)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("实际确认：¥450"))
        compose.onNodeWithText("实际确认：¥450").performScrollTo().assertIsDisplayed()
        assertEquals(retained, fixture.stored())

        stopModels()
        network.failReads = false
        installModels()
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 2L && history.state.value.total == 3 }
        assertEquals(2, network.confirms.size)
        assertEquals(retained, fixture.stored())
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("算了，不用还了"))
        compose.onNodeWithText("算了，不用还了").performScrollTo().performClick()
        compose.onNodeWithText("嗯，这份我请").performClick()
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.isForgiven == true }
        assertEquals(0L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals(450L, detail.value?.state?.value?.debt?.paidAmountCents)
        assertEquals(DebtForgiveCreateRequestDto(expectedRowVersion = 2), network.forgives.single().first)
        assertEquals(retained, fixture.stored())
    }

    @Test
    fun failedProposalReadOffersRetryBeforeClaimingEmptyOrAllowingForgiveness() {
        network.failProposalReads = true
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = skin) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { proposals.state.value.error != null }
        compose.onNodeWithText("算了，不用还了").assertDoesNotExist()
        compose.onNodeWithText("还没有新消息", substring = true).assertDoesNotExist()
        compose.onNodeWithText("收到啦，谢谢～").assertDoesNotExist()
        network.failProposalReads = false
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("重试"))
        saveConsumerArtPreview("member-debt-failed-read", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("重试").performScrollTo().performClick()
        compose.waitUntil(10_000) { proposals.state.value.pendingProposal != null }
        compose.onNodeWithText("收到啦，谢谢～").assertIsDisplayed()
        assertTrue(network.confirms.isEmpty() && network.proposes.isEmpty() && network.forgives.isEmpty())
    }

    @Test
    fun selectedPaymentDaySurvivesReturnRecreationAndOriginalSubmissionRecovery() {
        network.current = network.current.copy(viewerIsDebtor = true)
        network.hasProposal = false
        installModels()
        val retained = fixture.stored()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = skin) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt != null && proposals.state.value.hasReadableProposalState }
        compose.onNodeWithText("提交还款确认").performClick()
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("750")
        compose.onAllNodes(hasSetTextAction())[1].performTextReplacement("2026-04-")
        compose.onNodeWithText("返回，保留输入").performTouchInput { click() }
        compose.onNodeWithText("继续填写原还款").performClick()
        compose.onNodeWithText("2026-04-").assertIsDisplayed()
        compose.onAllNodes(hasSetTextAction())[1].performTextReplacement("2026-04-30")
        compose.onNodeWithText("2026-04-30").assertIsDisplayed()
        androidx.test.espresso.Espresso.closeSoftKeyboard()
        compose.waitForIdle()
        saveConsumerArtPreview("member-payment-date-form", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("¥450").performScrollTo().assertIsDisplayed()
        assertEquals(1200L, network.current.remainingAmountCents)
        compose.waitForIdle()
        saveConsumerArtPreview("member-payment-date-preview", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("提交还款确认").performTouchInput { click() }
        compose.waitUntil(10_000) { network.proposes.size == 1 && !proposals.state.value.isSubmitting }
        assertEquals(MemberRepaymentProposalCreateRequestDto(proposedAmountCents = 750,
            timeInput = ExpenseTimeInputDto(precision = "date_only", userLocalDate = "2026-04-30",
                accountingDate = "2026-04-30", sourceTimezone = "Asia/Shanghai", calendarRevision = 3)),
            network.proposes.single().first)
        stopModels()
        proposalSavedState = SavedStateHandle(proposalSavedState.keys().associateWith { proposalSavedState.get<Any?>(it) })
        network.current = network.current.copy(repaymentCalendar = com.ticketbox.data.remote.dto.RepaymentCalendarDto(4, "Pacific/Honolulu"))
        installModels()
        compose.waitUntil(10_000) { proposals.state.value.originalAttempt != null }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("原还款日：2026-04-30"))
        compose.onNodeWithText("原还款日：2026-04-30").assertIsDisplayed()
        compose.waitForIdle()
        saveConsumerArtPreview("member-payment-date-recovery", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("核实原提交结果").assertIsDisplayed().performClick()
        compose.waitUntil(10_000) { network.proposes.size == 2 && proposals.state.value.originalAttempt == null }
        assertEquals(network.proposes.first(), network.proposes.last())
        assertEquals("2026-04-30", proposals.state.value.pendingProposal?.accountingTime?.userLocalDate)
        assertEquals(retained, fixture.stored())
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            proposals = MemberRepaymentProposalViewModel(graph.debtRepository.proposals, proposalSavedState)
            history = DebtActivityViewModel(graph.debtRepository.activity)
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
