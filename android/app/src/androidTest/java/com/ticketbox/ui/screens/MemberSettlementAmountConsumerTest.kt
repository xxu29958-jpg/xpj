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

class MemberSettlementAmountConsumerTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun memberCanReadTheRemainingFrozenAmountBeforeOpeningAnotherControl() {
        val showDetail = mutableStateOf(false)
        val debt = Debt(
            publicId = "member-remaining",
            ledgerId = "owner",
            direction = DebtDirections.I_OWE,
            counterpartyType = DebtCounterpartyTypes.MEMBER,
            counterpartyAccountId = 42,
            counterpartyLabel = "小林",
            principalAmountCents = 1200,
            remainingAmountCents = 750,
            paidAmountCents = 450,
            status = DebtLinkStatuses.OPEN,
            sourceType = DebtSourceTypes.BILL_SPLIT,
            sourceId = "member-remaining-invitation",
            homeCurrencyCode = "JPY",
            originalCurrencyCode = null,
            originalAmountMinor = null,
            createdAt = "2026-09-08T00:00:00Z",
            updatedAt = "2026-09-08T00:00:00Z",
            rowVersion = 2,
            viewerIsDebtor = true,
        )
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                if (showDetail.value) MemberSharedThingCard(debt) else MemberDebtRow(debt)
            }
        }
        composeRule.onNodeWithText("¥750", substring = true).assertIsDisplayed()
        composeRule.runOnIdle { showDetail.value = true }
        composeRule.onNodeWithText("¥750", substring = true).assertIsDisplayed()
    }
}
