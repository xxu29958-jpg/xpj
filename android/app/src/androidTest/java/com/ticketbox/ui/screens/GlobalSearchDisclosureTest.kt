package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.GlobalSearchUiState
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

    private fun render(state: GlobalSearchUiState) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
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
                        onOpenExpense = {},
                    ),
                )
            }
        }
    }
}
