package com.ticketbox.ui.navigation

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * W2-C 主审定向回归：Relations 主 chrome 的真实呈现合同——
 * 创建链路错误（OCR 识别/准备失败、首载失败）必须在首屏可见（Danger banner），不得静默；
 * Viewer（canModify=false）不渲染新建/识别入口；可写时单主 CTA 真实可点。
 */
class ObligationsPrimaryChromeTest {

    @get:Rule
    val composeRule = createComposeRule()

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun setChrome(composer: RelationsComposerHandles) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ObligationsPrimaryChrome(
                    selectedView = ObligationsView.I_OWE,
                    onSelectView = {},
                    composer = composer,
                )
            }
        }
        composeRule.waitForIdle()
    }

    private fun handles(
        canModify: Boolean = true,
        error: UiText? = null,
        onAddDebt: () -> Unit = {},
        onRetry: () -> Unit = {},
    ) = RelationsComposerHandles(
        canModify = canModify,
        isParsingBill = false,
        flashMessage = null,
        error = error,
        actions = RelationsComposerActions(
            onRetry = onRetry,
            onAddDebt = onAddDebt,
            onParseBillImage = {},
        ),
    )

    @Test
    fun composerErrorSurfacesAsDangerBanner() {
        val errorText = context.getString(R.string.debt_bill_parse_failed)
        setChrome(handles(error = UiText.res(R.string.debt_bill_parse_failed)))

        composeRule.onNodeWithText(errorText).assertIsDisplayed()
    }

    @Test
    fun readOnlyLedgerHidesCreateEntries() {
        setChrome(handles(canModify = false))

        composeRule.onNodeWithText(context.getString(R.string.debt_list_add)).assertDoesNotExist()
    }

    @Test
    fun writableLedgerCtaInvokesComposer() {
        var addTapped = false
        setChrome(handles(onAddDebt = { addTapped = true }))

        composeRule.onNodeWithText(context.getString(R.string.debt_list_add)).performClick()
        composeRule.waitForIdle()

        assertTrue(addTapped)
    }

    @Test
    fun composerErrorOffersUserRetry() {
        // R1：错误不只要有 banner，还要能原地继续——重试入口可见且真实回调。
        var retryTapped = false
        setChrome(
            handles(
                error = UiText.res(R.string.debt_bill_parse_failed),
                onRetry = { retryTapped = true },
            ),
        )

        composeRule.onNodeWithText(context.getString(R.string.common_retry)).performClick()
        composeRule.waitForIdle()

        assertTrue(retryTapped)
    }
}
