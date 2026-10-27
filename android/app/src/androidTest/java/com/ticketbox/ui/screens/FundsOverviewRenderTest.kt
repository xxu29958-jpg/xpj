package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasScrollAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.domain.model.FundMovement
import com.ticketbox.domain.model.FundsOverview
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.FundsUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Synthetic accounts only: the overview, an account's changes and the confirm preview, at phone width and large text. */
class FundsOverviewRenderTest {

    @get:Rule
    val composeRule = createComposeRule()

    private val binding = LogicalSessionBinding("https://funds.example.test", "family", "owner", "session", "revision")

    @Test
    fun overviewGroupsAccountsAndFoldsArchivedOnes() {
        var opened = ""
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LazyColumn(Modifier.width(393.dp).padding(24.dp)) {
                    fundsOverview(overviewState(), FundsOverviewActions(open = { opened = it }, create = {}, envelopes = {}, resume = {}))
                }
            }
        }
        composeRule.onNodeWithText("日常账户").assertIsDisplayed()
        composeRule.onNodeWithText("信用账户").assertIsDisplayed()
        composeRule.onNodeWithText("欠款 ${money(3_790, "CNY")}").assertIsDisplayed()
        composeRule.onNodeWithText("结余 ${money(12_000, "CNY")}").assertIsDisplayed()
        composeRule.onNodeWithText("1 个账户余额待核对，暂未计入。").assertIsDisplayed()
        composeRule.onNodeWithText("旧工资卡 · 0042").assertDoesNotExist()
        saveConsumerArtPreview("funds-overview", composeRule.onRoot().captureToImage().asAndroidBitmap())

        composeRule.onNode(hasScrollAction()).performScrollToNode(hasText("已归档账户（1）"))
        composeRule.onNodeWithText("已归档账户（1）").performClick()
        composeRule.onNode(hasScrollAction()).performScrollToNode(hasText("旧工资卡 · 0042"))
        composeRule.onNodeWithText("旧工资卡 · 0042").performClick()
        assertEquals("archived", opened)
    }

    @Test
    fun emptyOverviewOffersTheFirstAccount() {
        var created = false
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LazyColumn(Modifier.width(393.dp).padding(24.dp)) {
                    fundsOverview(FundsUiState(access = LedgerAccessContext(binding, true)),
                        FundsOverviewActions(open = {}, create = { created = true }, envelopes = {}, resume = {}))
                }
            }
        }
        composeRule.onNodeWithText("从一张常用的卡开始").assertIsDisplayed()
        composeRule.onNodeWithText("添加账户").performClick()
        saveConsumerArtPreview("funds-empty", composeRule.onRoot().captureToImage().asAndroidBitmap())
        assertTrue(created)
    }

    @Test
    fun movementsSayWhatChangedWithSignedAmountsAtLargeText() {
        val credit = account("huabei", "花呗", "credit", -3_790)
        val movements = listOf(
            movement("draw", "credit_draw", -5_000, "超市"),
            movement("repay", "repayment", 1_210, "10 月账单还款"),
            movement("move", "transfer", -2_000, ""),
        )
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                val density = LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale = 2f)) {
                    LazyColumn(Modifier.width(320.dp).padding(16.dp)) {
                        item { FundsHeroCard(label = "当前欠款 · 按已记录的变动", amount = credit.balanceText()) {} }
                        items(movements, key = { it.publicId }) { row ->
                            FundsMovementRow(row, credit, FundsMovementActions(openExpense = {}, voidActivity = null, voidPayment = null, reconcile = null))
                        }
                    }
                }
            }
        }
        composeRule.onNodeWithText("信用消费").assertIsDisplayed()
        composeRule.onNodeWithText(money(-5_000, "CNY")).assertIsDisplayed()
        composeRule.onNodeWithText("+${money(1_210, "CNY")}").assertIsDisplayed()
        composeRule.onNodeWithText("转出").assertIsDisplayed()
        saveConsumerArtPreview("funds-movements-large-text", composeRule.onRoot().captureToImage().asAndroidBitmap())
    }

    @Test
    fun repaymentPreviewNamesBothAccountsBeforeConfirming() {
        val input = FundsInput(binding, "repay", "key", name = "花呗", currency = "CNY", payerId = "bank", payerName = "招商银行",
            payerCurrency = "CNY", principal = "37.90", paid = "37.90", newFee = "1.00")
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                Column(Modifier.width(393.dp).padding(24.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    FundsChangeSummary(input, emptyMap())
                }
            }
        }
        composeRule.onNodeWithText("从「招商银行」扣款：本金 37.90 CNY，新费用 1.00 CNY。「花呗」欠款减少 37.90 CNY。本金不再计一次消费；新费用记为一笔消费。")
            .assertIsDisplayed()
        saveConsumerArtPreview("funds-repay-preview", composeRule.onRoot().captureToImage().asAndroidBitmap())
    }

    private fun overviewState() = FundsUiState(
        overview = FundsOverview("CNY", "2026-10-19", 1_362_210, 3_790, 1_358_420, 4, 1, 0),
        accounts = listOf(
            account("bank", "招商银行", "bank", 1_276_210, tail = "8821"),
            account("cash", "现金", "cash", 86_000),
            account("wallet", "微信零钱", "wallet", null),
            account("huabei", "花呗", "credit", -3_790),
            account("card", "信用卡", "credit", 12_000),
            account("archived", "旧工资卡", "bank", 0, tail = "0042", archived = true),
        ),
    )

    private fun account(id: String, name: String, kind: String, balance: Long?, tail: String? = null, archived: Boolean = false) =
        FinancialAccount(publicId = id, name = name, ledgerId = "family", calendarRevision = 1, kind = kind, currencyCode = "CNY",
            visibility = "ledger", institution = null, tail = tail, rowVersion = 1, archived = archived, balanceMinor = balance,
            recordedChangeMinor = 0, openingDate = "2026-10-01", openingSource = "本人核对", debtPublicId = null, canEdit = true)

    private fun movement(id: String, kind: String, amount: Long, note: String) = FundMovement(publicId = id, eventPublicId = "event-$id",
        kind = kind, amountMinor = amount, occurredOn = "2026-10-18", note = note, expenseId = null, repaymentPublicId = null)
}
