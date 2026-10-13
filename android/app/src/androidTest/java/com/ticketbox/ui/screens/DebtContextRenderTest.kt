package com.ticketbox.ui.screens

import androidx.compose.runtime.mutableStateOf
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

class DebtContextRenderTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun summaryDisplaysCanonicalContextAndRemovesAbsentContext() {
        val note = "出差垫付车费\n待报销后归还"
        val current = mutableStateOf(
            Debt(
                publicId = "context-debt",
                ledgerId = "owner",
                direction = DebtDirections.I_OWE,
                counterpartyType = DebtCounterpartyTypes.EXTERNAL,
                counterpartyAccountId = null,
                counterpartyLabel = "同行人",
                principalAmountCents = 1200,
                remainingAmountCents = 1200,
                paidAmountCents = 0,
                status = DebtLinkStatuses.OPEN,
                sourceType = DebtSourceTypes.MANUAL,
                sourceId = null,
                homeCurrencyCode = "CNY",
                originalCurrencyCode = null,
                originalAmountMinor = null,
                createdAt = "2026-09-05T00:00:00Z",
                updatedAt = "2026-09-05T00:00:00Z",
                rowVersion = 1,
                note = note,
            ),
        )
        composeRule.setContent {
            TicketboxTheme(skin = if (androidx.test.platform.app.InstrumentationRegistry.getArguments()
                    .getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper) {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    DebtSummaryCard(current.value)
                }
            }
        }
        composeRule.onNodeWithText(note).performScrollTo().assertIsDisplayed()
        composeRule.onAllNodesWithText("未记录").assertCountEquals(2)
        composeRule.runOnIdle { current.value = current.value.copy(note = null,
            homeCurrencyCode = "JPY", principalAmountCents = 1200, paidAmountCents = 300,
            remainingAmountCents = 800, adjustmentAmountCents = -100, forgivenAmountCents = 0) }
        composeRule.onNodeWithText(note).assertDoesNotExist()
        composeRule.onNodeWithText("¥-100").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("剩余 · JPY").assertExists()
        composeRule.onNodeWithText("¥300").performScrollTo().assertIsDisplayed()
        composeRule.runOnIdle { current.value = current.value.copy(counterpartyType = DebtCounterpartyTypes.MEMBER,
            counterpartyAccountId = 2, viewerIsDebtor = true, status = DebtLinkStatuses.CLEARED,
            remainingAmountCents = 0, adjustmentAmountCents = 0, forgivenAmountCents = 900, isForgiven = true) }
        composeRule.onNodeWithText("¥900").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("¥300").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("debt-forgiven-breakdown", requireNotNull(
            androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }
}
