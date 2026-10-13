package com.ticketbox.ui.screens

import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.espresso.Espresso
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import com.ticketbox.domain.model.*
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.budget.BudgetHistorySheet
import com.ticketbox.ui.screens.plan.GoalHistorySheet
import com.ticketbox.ui.screens.recurring.RecurringHistorySheet
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.*
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

/** Production readers with controlled saved definitions; route/Room behavior has separate journey tests. */
class PlanHistoryPresentationTest {
    @get:Rule val compose = createComposeRule()
    private val more = mutableStateOf(false)
    private val open = mutableStateOf(true)
    private var reads = 0
    private val savedAt = "2026-10-03T06:20:00Z"
    private val fetchedAt = "2026-10-04T06:20:00Z"
    private val longAmount = InstrumentationRegistry.getArguments().getString("captureLongAmount") == "true"

    @Test fun budgetHistoryKeepsTheOriginalYenAcrossPages() = exercise("budget")
    @Test fun incomeHistoryKeepsTheOriginalYenAcrossPages() = exercise("income")
    @Test fun goalHistoryKeepsTheOriginalYenAcrossPages() = exercise("goal")
    @Test fun recurringHistoryKeepsTheOriginalYenAcrossPages() = exercise("recurring")

    private fun exercise(kind: String) {
        val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper
        compose.setContent { TicketboxTheme(skin = skin) {
            if (!open.value) Text("历史已关闭") else {
                val versions = if (more.value) listOf(3L, 2L) else listOf(3L)
                val next = if (more.value) null else 3L
                val onMore = { reads += 1; more.value = true }
                val dismiss = { open.value = false }
                when (kind) {
                    "budget" -> BudgetHistorySheet(BudgetHistoryState("2026-10", versions.map(::budget), next,
                        fetchedAt = fetchedAt, fromCache = true), {}, onMore, dismiss)
                    "income" -> IncomeHistorySheet(IncomeHistoryState("income", versions.map(::income), next,
                        fetchedAt = fetchedAt, fromCache = true), {}, onMore, dismiss)
                    "goal" -> GoalHistorySheet(GoalHistoryState(true, versions.map(::goal), next,
                        fetchedAt = fetchedAt, fromCache = true), {}, onMore, dismiss)
                    "recurring" -> RecurringHistorySheet(RecurringHistoryState("series", "家庭固定支出", versions.map(::recurring), next,
                        fetchedAt = fetchedAt, fromCache = true), {}, onMore, dismiss)
                }
            }
        } }
        capture("history-$kind-first-page")
        compose.onNodeWithText("已载入 1 条 · 第 3 至 3 版").assertExists()
        compose.onNodeWithText("上一版尚未载入，暂时无法核对修改前的值。").assertExists()
        compose.onNodeWithText("修改前").assertDoesNotExist()
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        compose.waitForIdle()
        capture("history-$kind-adjacent")
        compose.onNodeWithText("已载入 2 条 · 第 3 至 2 版").assertExists()
        compose.onNodeWithText("修改前").performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("JPY ¥3,800")[0].assertExists()
        compose.onNodeWithText(if (kind == "budget" && longAmount) "CNY ¥98,765,432,100.99" else "CNY ¥4,000.00").assertExists()
        if (kind == "budget" && longAmount) {
            val layouts = mutableListOf<TextLayoutResult>()
            compose.onNodeWithText("CNY ¥98,765,432,100.99").performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            val layout = layouts.single()
            val text = layout.layoutInput.text.text
            assertFalse(layout.hasVisualOverflow)
            assertEquals("The full numeric amount must stay together", layout.getLineForOffset(text.indexOf('¥')),
                layout.getLineForOffset(text.lastIndex))
        }
        compose.onNodeWithText("修改后").performScrollTo().assertIsDisplayed()
        capture("history-$kind-comparison")
        compose.onAllNodesWithText("查看当时定义")[0].performScrollTo().performClick()
        compose.onNodeWithText("收起当时定义").assertExists()
        capture("history-$kind-definition")
        assertEquals(1, reads)
        com.ticketbox.ui.RealKeyboard().dismissAndWait(compose)
        Espresso.pressBack()
        try {
            compose.waitUntil(5_000) { !open.value && compose.onNodeWithText("历史已关闭").isDisplayed() }
        } catch (failure: ComposeTimeoutException) {
            val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
            runCatching { automation.takeScreenshot()?.let { saveConsumerArtPreview("history-$kind-back-failure", it) } }
            println("History dismissal timed out: kind=$kind open=${open.value}")
            throw failure
        }
        compose.onNodeWithText("历史已关闭").assertIsDisplayed()
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        saveConsumerArtPreview(name, compose.onNode(hasScrollAction()).captureToImage().asAndroidBitmap())
    }
    private fun kind(version: Long) = if (version == 2L) "baseline" else "edit"
    private fun currency(version: Long) = if (version == 2L) "JPY" else "CNY"
    private fun amount(version: Long) = if (version == 2L) 3800L else 400000L
    private fun budget(version: Long) = BudgetRevision(version, kind(version), savedAt,
        BudgetArrangement(currency(version), if (version == 3L && longAmount) 9876543210099L else amount(version), 2000, -500, listOf("家庭长期安排的完整分类名称"),
            listOf(BudgetCategoryArrangement("餐饮与日常采购", 900)), false))
    private fun income(version: Long) = IncomeRevision(version, kind(version), savedAt, "2026-10", "2026-10",
        IncomeDefinition("家庭工作收入的完整计划名称", "salary", "monthly", null, amount(version), currency(version), 31, "active"))
    private fun goal(version: Long) = GoalRevision(version, kind(version), savedAt,
        GoalDefinition("家庭学习与交通的完整目标名称", "spending", "monthly", "2026-10", "日常交通", amount(version), currency(version), "active"))
    private fun recurring(version: Long) = RecurringRevisionDto(version, kind(version), savedAt, null,
        RecurringDefinitionDto("家庭宽带与通信服务的完整名称", "original", "monthly", currency(version), amount(version), "2026-10-09", "active", "manual"))
}
