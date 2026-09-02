package com.ticketbox.ui.screens

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtRepaymentStatuses
import com.ticketbox.domain.model.DebtRepaymentVoid
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.displayDate
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtRepaymentHistoryUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * W2-C production-consumer regression：还款记录段的真实渲染合同——
 * 行金额/日期/作废原因、分页 footer 只在确有上下页时出现、Viewer/整笔已作废/成员欠款无作废入口、
 * 加载失败段内提示+重试且不吞列表。只读历史；命令资格仍由服务端 guard 最终裁决。
 */
class DebtRepaymentHistorySectionRenderTest {

    @get:Rule
    val composeRule = createComposeRule()

    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    private fun debt(
        status: String = DebtLinkStatuses.OPEN,
        counterpartyType: String = DebtCounterpartyTypes.EXTERNAL,
    ): Debt = Debt(
        publicId = "debt-1",
        ledgerId = "owner",
        direction = DebtDirections.I_OWE,
        counterpartyType = counterpartyType,
        counterpartyAccountId = null,
        counterpartyLabel = "对手方",
        principalAmountCents = 10_000,
        remainingAmountCents = 4_000,
        paidAmountCents = 6_000,
        status = status,
        sourceType = DebtSourceTypes.MANUAL,
        sourceId = null,
        homeCurrencyCode = "CNY",
        originalCurrencyCode = null,
        originalAmountMinor = null,
        createdAt = "2026-06-18T00:00:00Z",
        updatedAt = "2026-06-18T00:00:00Z",
        rowVersion = 1,
    )

    private fun repayment(
        id: String,
        cents: Long,
        status: String = DebtRepaymentStatuses.ACTIVE,
        voidReason: String? = null,
    ): DebtRepayment = DebtRepayment(
        publicId = id,
        amountCents = cents,
        paidAt = "2026-06-18T00:00:00Z",
        createdAt = "2026-06-18T00:00:00Z",
        status = status,
        voidFact = voidReason?.let { DebtRepaymentVoid(publicId = "void-$id", reason = it, createdAt = "2026-06-19T00:00:00Z") },
    )

    private fun render(
        currentDebt: () -> Debt = { debt() },
        canModify: () -> Boolean = { true },
        history: () -> DebtRepaymentHistoryUiState,
        onVoidRepayment: (DebtRepayment) -> Unit = {},
    ) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                DebtRepaymentHistorySection(
                    debt = currentDebt(),
                    canModify = canModify(),
                    history = history(),
                    callbacks = DebtRepaymentHistoryCallbacks(
                        onVoidRepayment = onVoidRepayment,
                        onLoadPage = {},
                        onRetry = {},
                    ),
                )
            }
        }
    }

    @Test
    fun rowsShowAmountDateAndVoidedReason() {
        render(
            history = {
                DebtRepaymentHistoryUiState(
                    debtPublicId = "debt-1",
                    homeCurrencyCode = "CNY",
                    items = listOf(
                        repayment("r1", 6_000),
                        repayment("r2", 2_500, status = DebtRepaymentStatuses.VOIDED, voidReason = "记错了"),
                    ),
                    page = 1,
                    total = 2,
                )
            },
        )

        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_title)).assertExists()
        composeRule.onNodeWithText("¥60.00").assertExists()
        composeRule.onNodeWithText("¥25.00").assertExists()
        composeRule.onAllNodesWithText(displayDate("2026-06-18T00:00:00Z")).assertCountEquals(2)
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_voided_badge)).assertExists()
        composeRule
            .onNodeWithText(context.getString(R.string.debt_repayment_voided_reason, "记错了"))
            .assertExists()
    }

    @Test
    fun voidEntryOnlyForActiveRepaymentOnDirectWritableDebt() {
        var voided: DebtRepayment? = null
        render(
            history = {
                DebtRepaymentHistoryUiState(
                    debtPublicId = "debt-1",
                    homeCurrencyCode = "CNY",
                    items = listOf(
                        repayment("r1", 6_000),
                        repayment("r2", 2_500, status = DebtRepaymentStatuses.VOIDED, voidReason = "记错了"),
                    ),
                    page = 1,
                    total = 2,
                )
            },
            onVoidRepayment = { voided = it },
        )

        val entries = composeRule.onAllNodesWithText(context.getString(R.string.debt_repayment_void_action))
        entries.assertCountEquals(1)
        entries[0].performClick()
        assertEquals("r1", voided?.publicId)
    }

    @Test
    fun viewerAndTerminalVoidedAndMemberDebtSeeNoVoidEntry() {
        val history = DebtRepaymentHistoryUiState(
            debtPublicId = "debt-1",
            homeCurrencyCode = "CNY",
            items = listOf(repayment("r1", 6_000)),
            page = 1,
            total = 1,
        )
        val voidLabel = context.getString(R.string.debt_repayment_void_action)
        val currentDebt = mutableStateOf(debt())
        val canModify = mutableStateOf(false)

        render(
            currentDebt = { currentDebt.value },
            canModify = { canModify.value },
            history = { history },
        )
        composeRule.onNodeWithText(voidLabel).assertDoesNotExist()

        composeRule.runOnIdle {
            canModify.value = true
            currentDebt.value = debt(status = DebtLinkStatuses.VOIDED)
        }
        composeRule.onNodeWithText(voidLabel).assertDoesNotExist()

        composeRule.runOnIdle {
            currentDebt.value = debt(counterpartyType = DebtCounterpartyTypes.MEMBER)
        }
        composeRule.onNodeWithText(voidLabel).assertDoesNotExist()
    }

    @Test
    fun pagerAppearsOnlyWhenMorePagesExist() {
        val history = mutableStateOf(
            DebtRepaymentHistoryUiState(
                debtPublicId = "debt-1",
                homeCurrencyCode = "CNY",
                items = listOf(repayment("r1", 6_000)),
                page = 2,
                total = 3,
                hasNext = true,
            ),
        )
        render(history = { history.value })
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_newer)).assertExists()
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_older)).assertExists()
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_total, 3)).assertExists()

        composeRule.runOnIdle {
            history.value = DebtRepaymentHistoryUiState(
                debtPublicId = "debt-1",
                homeCurrencyCode = "CNY",
                items = listOf(repayment("r1", 6_000)),
                page = 1,
                total = 1,
            )
        }
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_newer)).assertDoesNotExist()
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_older)).assertDoesNotExist()
    }

    @Test
    fun loadFailureShowsBannerAndRetryWithoutBlockingContent() {
        render(
            history = {
                DebtRepaymentHistoryUiState(
                    debtPublicId = "debt-1",
                    homeCurrencyCode = "CNY",
                    items = listOf(repayment("r1", 6_000)),
                    page = 1,
                    total = 1,
                    error = UiText.raw("offline"),
                )
            },
        )
        composeRule.onNodeWithText("offline").assertExists()
        composeRule.onNodeWithText(context.getString(R.string.common_retry)).assertExists()
        // 已有记录不被错误吞掉（查询失败不阻断读，也不阻断上方命令区）。
        composeRule.onNodeWithText("¥60.00").assertExists()
    }

    @Test
    fun emptyHistoryIsHonest() {
        render(
            history = {
                DebtRepaymentHistoryUiState(
                    debtPublicId = "debt-1",
                    homeCurrencyCode = "CNY",
                    items = emptyList(),
                    page = 1,
                    total = 0,
                )
            },
        )
        composeRule.onNodeWithText(context.getString(R.string.debt_repayment_history_empty)).assertExists()
    }
}
