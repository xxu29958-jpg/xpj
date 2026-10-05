package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.GlobalSearchUiState
import com.ticketbox.viewmodel.GlobalSearchResultUi
import com.ticketbox.viewmodel.GlobalSearchResultKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * W2-B 搜索页渐进披露：默认只露月份 + 「更多分类」入口，关键词任务与结果
 * 不被全量分类 chip 挤下首屏；展开后全部分类可达；已有选中分类时自动展开
 * （选中态必须可见且可取消）。
 */
class GlobalSearchDisclosureTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun categoriesCollapsedByDefaultAndExpandOnDemand() {
        render(GlobalSearchUiState(availableCategories = listOf("餐饮", "交通")))

        composeRule.onAllNodesWithText("餐饮").assertCountEquals(0)
        composeRule.onNodeWithText("更多分类").performClick()
        composeRule.onNodeWithText("餐饮").assertExists()
    }

    @Test
    fun selectedCategoryAutoExpandsAndStaysRemovable() {
        render(
            GlobalSearchUiState(
                availableCategories = listOf("餐饮", "交通"),
                categoryFilter = "餐饮",
            ),
        )

        composeRule.onNodeWithText("餐饮").assertExists()
        composeRule.onNodeWithText("全部分类").assertExists()
        composeRule.onAllNodesWithText("更多分类").assertCountEquals(0)
    }

    @Test fun matchingResultKeepsTheOriginalDestination() = readableResult(12_860, "search-result")

    @Test fun longNameAndAmountStayReadable() = readableResult(Long.MAX_VALUE, "search-result-long")

    private fun readableResult(amount: Long, name: String) {
        val merchant = if (amount == Long.MAX_VALUE) "需要完整识别的家庭日用百货便利店长名称" else "便利店"
        val expense = ExpenseDto(id = 42, publicId = "search-42", amountCents = amount,
            homeCurrency = "CNY", originalCurrency = "CNY", originalCurrencyCode = "CNY", originalAmountMinor = amount,
            merchant = merchant, category = "购物", note = null, source = "manual", imagePath = null, thumbnailPath = null,
            imageHash = null, rawText = null, confidence = null, duplicateStatus = "none", duplicateOfId = null,
            duplicateReason = null, tags = null, valueScore = null, regretScore = null, status = "confirmed",
            expenseTime = "2026-10-03T12:00:00Z", createdAt = "2026-10-03T12:00:00Z", updatedAt = "2026-10-03T12:00:00Z",
            rowVersion = 2, confirmedAt = "2026-10-03T12:00:00Z", rejectedAt = null).toDomain()
        var opened: Long? = null
        render(GlobalSearchUiState(query = "便利店", pendingLoaded = true, confirmedMatchCount = 1,
            results = listOf(GlobalSearchResultUi(GlobalSearchResultKind.Confirmed, expense, merchant, UiText.raw("商家"))))) {
            opened = it
        }
        val amountText = formatDisplayAmount(amount, CurrencyDisplay.forRecord("CNY"))
        composeRule.onNodeWithText(amountText, useUnmergedTree = true).performScrollTo()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        composeRule.waitForIdle()
        com.ticketbox.ui.saveConsumerArtPreview(name, requireNotNull(instrumentation.uiAutomation.takeScreenshot()))
        for (text in listOf(merchant, amountText)) {
            val layouts = mutableListOf<TextLayoutResult>()
            composeRule.onNode(hasText(text) and !hasSetTextAction(), useUnmergedTree = true)
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            assertTrue("Search must display all of $text", layouts.isNotEmpty() && layouts.all { layout ->
                !layout.didOverflowHeight && (0 until layout.lineCount).all { line ->
                    !layout.isLineEllipsized(line) && layout.getLineRight(line) <= layout.size.width
                }
            })
        }
        composeRule.onNode(hasText(merchant) and !hasSetTextAction()).performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(42L, opened) }
    }

    private fun render(state: GlobalSearchUiState, onOpenExpense: (Long) -> Unit = {}) {
        composeRule.setContent {
            val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                AppSkin.Midnight else AppSkin.Paper
            TicketboxTheme(skin = skin) {
                GlobalSearchScreen(
                    state = state,
                    actions = GlobalSearchActionsUi(
                        onQueryChange = {},
                        onScopeChange = {},
                        onCategoryChange = {},
                        onMonthChange = {},
                        onCommitSearch = {},
                        onApplyRecentSearch = {},
                        onClearRecentSearches = {},
                        onRefreshPending = {},
                        onOpenExpense = onOpenExpense,
                    ),
                    onBack = {},
                )
            }
        }
    }
}
