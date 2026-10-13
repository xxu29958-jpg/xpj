package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.expense.fact.ExpenseFactScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.loadExpenseFactBundle
import com.ticketbox.viewmodel.OffsetFormField
import com.ticketbox.viewmodel.updateOffsetFormField
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Production sheet and Room input; viewing an impact never creates a financial command. */
class ExpenseOffsetFlowRenderTest {
    @get:Rule val compose = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val fixture = ExpenseCorrectionConnectedFixture(context)
    private lateinit var model: ExpenseFactViewModel

    @After fun close() {
        if (::model.isInitialized) compose.runOnIdle { model.viewModelScope.cancel() }
        fixture.close()
    }

    @Test fun refundKeepsItsInputWhenReturningToTheBill() {
        showBill()
        compose.onNodeWithText(context.getString(R.string.expense_fact_offsets_title)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.expense_offset_create_refund_cta)).performScrollTo().performClick()
        compose.runOnIdle {
            model.updateOffsetFormField(OffsetFormField.Amount, "20.00")
            model.updateOffsetFormField(OffsetFormField.Reason, "退回未提供的餐品")
        }
        compose.onNodeWithText("退回未提供的餐品").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("登记退回").performScrollTo().assertIsDisplayed()
        capture("refund-overview")
        compose.onNodeWithText("当前可退 ¥120.00 − 本次 20.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥100.00").assertIsDisplayed()
        capture("refund-form")
        compose.onNodeWithText("银行拒付").performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.expense_fact_input_close)).performClick()
        compose.onNodeWithText(context.getString(R.string.expense_offset_create_refund_cta)).performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals("20.00", model.uiState.value.offsetForm.amountText)
            assertEquals("退回未提供的餐品", model.uiState.value.offsetForm.reason)
        }
        assertEquals(0, fixture.stored().size)
        fixture.network.failReads = true
        compose.runOnIdle { model.loadExpenseFactBundle() }
        compose.waitUntil(10_000) { model.uiState.value.factBundleLoadState == ExpenseDetailDataLoadState.Failed }
        compose.onNodeWithText("¥100.00").assertDoesNotExist()
        compose.runOnIdle { assertEquals("20.00", model.uiState.value.offsetForm.amountText) }
    }

    @Test fun reversalRequiresReviewWithoutCreatingAZeroAmountBill() {
        showBill()
        compose.onNodeWithText(context.getString(R.string.expense_fact_offsets_title)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.expense_offset_create_reversal_cta)).performScrollTo().performClick()
        compose.runOnIdle {
            model.updateOffsetFormField(OffsetFormField.Reason, "重复确认，经核对后冲销")
        }
        val submit = compose.onNodeWithText(context.getString(R.string.expense_offset_submit_reversal))
        submit.assertIsNotEnabled()
        compose.onNodeWithText("我已核对原件与关联记录").performScrollTo().performClick()
        submit.assertIsEnabled()
        capture("reversal-form")
        compose.onNodeWithText(context.getString(R.string.expense_fact_input_close)).performClick()
        compose.onNodeWithText(context.getString(R.string.expense_offset_create_reversal_cta)).performScrollTo().performClick()
        submit.assertIsNotEnabled()
        compose.runOnIdle { assertEquals(12_000L, model.uiState.value.expense?.originalAmountMinor) }
        assertEquals(0, fixture.stored().size)
    }

    private fun showBill() {
        fixture.network.current = fixture.network.current.copy(merchant = "街角小馆", amountCents = 12_000,
            originalAmountMinor = 12_000)
        val graph = fixture.reopen()
        compose.runOnIdle { model = ExpenseFactViewModel(42, graph.expenseRepository) }
        compose.setContent {
            val state by model.uiState.collectAsState()
            val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                AppSkin.Midnight else AppSkin.Paper
            TicketboxTheme(skin = skin) { ExpenseFactScreen(state, model, {}, { _, _ -> }) }
        }
        compose.waitUntil(10_000) { model.uiState.value.factInputsReady && model.uiState.value.authoritativeRootReady }
    }

    private fun capture(name: String) {
        compose.mainClock.advanceTimeBy(500)
        compose.waitForIdle()
        instrumentation.uiAutomation.waitForIdle(300, 3_000)
        com.ticketbox.ui.saveConsumerArtPreview(name, requireNotNull(instrumentation.uiAutomation.takeScreenshot()))
    }
}
