package com.ticketbox.ui.screens

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
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
            TicketboxTheme(skin = AppSkin.Paper) { DebtSummaryCard(debt = current.value) }
        }
        composeRule.onNodeWithText(note).assertIsDisplayed()
        composeRule.runOnIdle { current.value = current.value.copy(note = null) }
        composeRule.onNodeWithText(note).assertDoesNotExist()
    }
}
