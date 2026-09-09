package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.StreamOffset
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.screens.ledger.LedgerDayHeader
import com.ticketbox.ui.screens.ledger.LedgerDayHeaderUi
import com.ticketbox.ui.screens.ledger.LedgerHeader
import com.ticketbox.ui.screens.ledger.LedgerExpenseCard
import com.ticketbox.ui.screens.ledger.LedgerExpenseItemActions
import com.ticketbox.ui.screens.ledger.LedgerExpenseItemState
import com.ticketbox.ui.screens.ledger.LedgerExpenseListRow
import com.ticketbox.ui.screens.ledger.LedgerExpenseSelectionState
import com.ticketbox.ui.screens.ledger.LedgerExpenseTableRow
import com.ticketbox.ui.screens.ledger.LedgerOffsetItemState
import com.ticketbox.ui.screens.ledger.LedgerOffsetRow
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.LedgerUiState
import org.junit.Rule
import org.junit.Test

class LedgerCurrencyHeaderTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun pageAndDayHeadersKeepCapturedCurrenciesDespiteAmbientCurrency() {
        val root = ledgerHeaderConfirmedRow(100L) as ConfirmedStreamItem.ExpenseRow
        val yen = root.copy(root = root.root.copy(id = 2, homeCurrencyCode = "JPY"))
        val refund = ConfirmedStreamItem.OffsetRow(
            streamDate = root.streamDate, streamAmountCents = -150L, root = root.root,
            lineageStatus = ExpenseLineageStatus.PartiallyRefunded, lineageHomeNetCents = 0L,
            offset = StreamOffset("yen-refund", StreamOffsetKind.Refund, 150L, 150L, "JPY", "JPY", "餐饮"),
        )
        val state = LedgerUiState(items = listOf(root, yen, refund))
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CompositionLocalProvider(LocalCurrencyCode provides CurrencyCode.EUR) {
                    androidx.compose.foundation.layout.Column(Modifier.width(328.dp)) {
                        LedgerHeader(state)
                        LedgerDayHeader(LedgerDayHeaderUi("9月1日", state.summary.amountsByCurrency, 3))
                    }
                }
            }
        }
        composeRule.onAllNodesWithText("CNY ¥1.00").assertCountEquals(2)
        composeRule.onAllNodesWithText("CNY ¥1.00")[0].assertIsDisplayed()
        composeRule.onAllNodesWithText("CNY ¥1.00")[1].assertIsDisplayed()
        composeRule.onAllNodesWithText("JPY ¥-50").assertCountEquals(2)
        composeRule.onAllNodesWithText("JPY ¥-50")[0].assertIsDisplayed()
        composeRule.onAllNodesWithText("JPY ¥-50")[1].assertIsDisplayed()
        composeRule.onAllNodesWithText("€", substring = true).assertCountEquals(0)
    }

    @Test
    fun unknownCurrencyNeverRendersAnAmbientYuanTotal() {
        val root = ledgerHeaderConfirmedRow(100L) as ConfirmedStreamItem.ExpenseRow
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LedgerHeader(LedgerUiState(items = listOf(root.copy(root = root.root.copy(homeCurrencyCode = null)))))
            }
        }
        composeRule.onNodeWithText("部分记录币种待核对").assertIsDisplayed()
        composeRule.onAllNodesWithText("¥", substring = true).assertCountEquals(0)
        composeRule.onNodeWithText("1 笔", substring = true).assertIsDisplayed()
    }

    @Test
    fun allRootLayoutsKeepMissingCurrencyExplicit() {
        val root = (ledgerHeaderConfirmedRow(100L) as ConfirmedStreamItem.ExpenseRow).root
        val state = LedgerExpenseItemState(root.copy(homeCurrencyCode = null), LedgerExpenseSelectionState(false, false))
        val actions = LedgerExpenseItemActions({}, {}, {})
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                androidx.compose.foundation.layout.Column(Modifier.width(328.dp)) {
                    LedgerExpenseCard(state, actions)
                    LedgerExpenseListRow(state.copy(expense = root.copy(homeCurrencyCode = "  ")), actions)
                    LedgerExpenseTableRow(state, actions)
                }
            }
        }
        composeRule.onAllNodesWithText("币种待核对").assertCountEquals(3)
        composeRule.onAllNodesWithText("币种待核对")[0].assertIsDisplayed()
        composeRule.onAllNodesWithText("币种待核对")[1].assertIsDisplayed()
        composeRule.onAllNodesWithText("币种待核对")[2].assertIsDisplayed()
        composeRule.onAllNodesWithText("¥", substring = true).assertCountEquals(0)
        composeRule.onAllNodesWithText("咖啡店").assertCountEquals(3)
    }

    @Test
    fun refundRowsKeepOriginalCurrencyAndNeverInventMissingCurrency() {
        val root = ledgerHeaderConfirmedRow(100L) as ConfirmedStreamItem.ExpenseRow
        val refund = ConfirmedStreamItem.OffsetRow(
            streamDate = root.streamDate, streamAmountCents = -150L, root = root.root,
            lineageStatus = ExpenseLineageStatus.PartiallyRefunded, lineageHomeNetCents = 0L,
            offset = StreamOffset("refund", StreamOffsetKind.Refund, 150L, 100L,
                originalCurrencyCode = "USD", homeCurrencyCode = "JPY", category = "餐饮"),
        )
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default, currency = CurrencyCode.EUR) {
                androidx.compose.foundation.layout.Column(Modifier.width(328.dp)) {
                    LedgerOffsetRow(LedgerOffsetItemState(refund), {})
                    LedgerOffsetRow(LedgerOffsetItemState(refund.copy(
                        offset = refund.offset.copy(publicId = "unknown", originalCurrencyCode = " "),
                    )), {})
                }
            }
        }
        composeRule.onNodeWithText("+$1.00").assertIsDisplayed()
        composeRule.onNodeWithText("币种待核对").assertIsDisplayed()
        composeRule.onAllNodesWithText("¥", substring = true).assertCountEquals(0)
        composeRule.onAllNodesWithText("€", substring = true).assertCountEquals(0)
    }

}
