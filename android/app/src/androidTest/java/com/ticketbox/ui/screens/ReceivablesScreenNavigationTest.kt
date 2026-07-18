package com.ticketbox.ui.screens

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.data.repository.ReceivablesActions
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ReceivablesViewModel
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * 个人应收可同时包含 member 与 external。点击任一行必须把那笔 [Debt] 交给
 * [onOpenReceivable]；本测试用 external 第二行钉住 mixed projection 与逐行回调接线。
 */
class ReceivablesScreenNavigationTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun tappingReceivableRowOpensThatDebtsDetail() {
        var openedPublicId: String? = null
        // Construct the VM outside the composable (lint ViewModelConstructorInComposable); the test
        // drives the real ReceivablesViewModel over a fake actions surface. Two distinct rows so
        // tapping the SECOND pins the per-row binding `onOpenReceivable(debt)` — a first()/index-0
        // mutation (wrong-debt capture) would open "debt-1" and fail the assert.
        val viewModel = ReceivablesViewModel(
            FakeReceivables(
                listOf(
                    memberReceivable(publicId = "debt-1", debtorName = "小明"),
                    externalReceivable(publicId = "debt-2", debtorName = "阿禾"),
                ),
            ),
        )

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ReceivablesScreen(
                    viewModel = viewModel,
                    currency = CurrencyDisplay.LegacyFallback,
                    onOpenReceivable = { openedPublicId = it.publicId },
                    onBack = {},
                )
            }
        }

        // The VM loads on a viewModelScope coroutine; wait for the row to render before clicking.
        composeRule.waitUntil(timeoutMillis = 5_000) {
            composeRule.onAllNodesWithText("阿禾").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("阿禾").performClick()

        composeRule.runOnIdle { assertEquals("debt-2", openedPublicId) }
    }
}

private class FakeReceivables(private val rows: List<Debt>) : ReceivablesActions {
    override suspend fun listReceivables(): Result<List<Debt>> = Result.success(rows)
}

// A cross-ledger member receivable: viewer is the creditor (viewerIsDebtor=false), ledger id redacted
// (§5.2), an open bill_split obligation — the shape the route opens into the creditor confirm flow.
private fun memberReceivable(publicId: String, debtorName: String): Debt = Debt(
    publicId = publicId,
    ledgerId = null,
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.MEMBER,
    counterpartyAccountId = 7L,
    counterpartyLabel = debtorName,
    principalAmountCents = 10_000,
    remainingAmountCents = 4_000,
    paidAmountCents = 6_000,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.BILL_SPLIT,
    sourceId = "inv-1",
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-01T00:00:00Z",
    updatedAt = "2026-06-01T00:00:00Z",
    rowVersion = 3,
    viewerIsDebtor = false,
    isForgiven = false,
)

private fun externalReceivable(publicId: String, debtorName: String): Debt =
    memberReceivable(publicId, debtorName).copy(
        ledgerId = "owner",
        direction = DebtDirections.OWED_TO_ME,
        counterpartyType = DebtCounterpartyTypes.EXTERNAL,
        counterpartyAccountId = null,
        sourceType = DebtSourceTypes.MANUAL,
        sourceId = null,
        viewerIsDebtor = null,
    )
