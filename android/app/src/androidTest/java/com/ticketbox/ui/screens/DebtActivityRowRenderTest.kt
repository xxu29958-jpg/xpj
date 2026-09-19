package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtRepaymentVoid
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class DebtActivityRowRenderTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun proposalCreationAndResolutionShowOneActualConfirmationAndOpenItsExactPayment() {
        val proposal = partialProposal()
        var opened: String? = null
        val events = listOf(
            activity("proposal_created", "proposal-1").copy(proposal = proposal),
            activity("proposal_resolved", "proposal-1").copy(proposal = proposal),
        )
        render(events, open = { opened = it })
        compose.onAllNodesWithText("申报金额：¥100.00").assertCountEquals(2)
        compose.onAllNodesWithText("实际确认：¥40.00").assertCountEquals(1)
        compose.onNodeWithText(context.getString(R.string.debt_proposal_status_partially_confirmed)).performScrollTo().assertExists()
        compose.onNodeWithText("查看关联还款").performScrollTo().performClick()
        assertEquals("payment-accepted", opened)
        compose.onAllNodesWithText("先还这部分").assertCountEquals(2)
    }

    @Test
    fun originalPaymentAndVoidKeepForeignAmountFrozenFxAndReason() {
        val payment = DebtRepayment("payment-1", 700, "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "voided",
            DebtRepaymentVoid("void-1", "重复收款", "2026-09-03T00:00:00Z"), "USD", 100, "7.0", "2026-09-01", "manual")
        render(listOf(activity("repayment_void", "void-1").copy(repayment = payment, reason = "重复收款")))
        compose.onNodeWithText(context.getString(R.string.debt_activity_repayment_void)).assertExists()
        compose.onNodeWithText("¥7.00").assertExists()
        compose.onNodeWithText(context.getString(R.string.debt_repayment_original_amount, "$1.00")).assertExists()
        compose.onNodeWithText("冻结汇率：7.0 · 2026-09-01 · 手动汇率").assertExists()
        compose.onNodeWithText("manual", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.debt_repayment_voided_reason, "重复收款")).assertExists()
        compose.onNodeWithText(context.getString(R.string.debt_repayment_void_action)).assertDoesNotExist()
    }

    @Test
    fun creationAdjustmentForgivenessAndWholeVoidRemainDistinctRecords() {
        render(listOf(
            activity("created", "debt-1").copy(amountCents = 10000),
            activity("adjustment", "adjust-1").copy(amountCents = -500, reason = "退回部分"),
            activity("forgiveness", "forgive-1").copy(amountCents = 500),
            activity("debt_void", "void-1").copy(reason = "整笔重复"),
        ))
        for (kind in listOf("created", "adjustment", "forgiveness", "debt_void")) {
            compose.onNodeWithText(context.getString(debtActivityKindLabel(kind))).performScrollTo().assertExists()
        }
        compose.onNodeWithText("整笔重复").performScrollTo().assertExists()
        compose.onNodeWithText("退回部分").performScrollTo().assertExists()
    }

    private fun render(events: List<DebtActivity>, open: (String) -> Unit = {}) {
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    events.forEach { event ->
                        DebtActivityRow(DebtActivityRowState(event, "CNY", false, false, false),
                            DebtActivityCallbacks({}, {}, {}, open))
                    }
                }
            }
        }
    }
}

private fun activity(kind: String, id: String) = DebtActivity(kind, id, "2026-09-03T00:00:00Z", "对方", false)

private fun partialProposal() = MemberRepaymentProposal(
    publicId = "proposal-1", debtPublicId = "debt-1", status = "partially_confirmed",
    proposedAmountCents = 10000, confirmedAmountCents = 4000, homeCurrencyCode = "CNY",
    originalCurrencyCode = null, originalAmountMinor = null, paidAt = "2026-09-01T00:00:00Z", note = "先还这部分",
    expiresAt = "2026-10-01T00:00:00Z", createdAt = "2026-09-02T00:00:00Z", resolvedAt = "2026-09-03T00:00:00Z",
    supersedesProposalPublicId = null, committedRepaymentPublicId = "payment-accepted",
)
