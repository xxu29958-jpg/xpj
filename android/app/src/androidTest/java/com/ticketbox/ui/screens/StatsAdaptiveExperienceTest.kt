package com.ticketbox.ui.screens

import androidx.compose.material3.adaptive.layout.PaneScaffoldDirective
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.ForcedSize
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.ui.screens.stats.DashboardLayoutActions
import com.ticketbox.ui.screens.stats.OverviewModuleActions
import com.ticketbox.ui.screens.stats.OverviewModulesState
import com.ticketbox.ui.screens.stats.OverviewInteractionActions
import com.ticketbox.viewmodel.DashboardLayoutUiState
import com.ticketbox.viewmodel.RecurringUiState
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.LocalAppAdaptivePaneDirective
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAdaptivePaneMode
import com.ticketbox.ui.design.AppAdaptivePostureConstraint
import com.ticketbox.ui.design.AppPrimaryNavigationMode
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.StatsFilterOptionsLoadState
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class StatsAdaptiveExperienceTest {
    @get:Rule
    val composeRule = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun flatWindowsKeepFiltersAndTabsWithTheirResults() {
        val viewport = mutableStateOf(360.dp to AppAdaptiveLayoutPolicy.Compact)
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(viewport.value.first, 900.dp))) {
                TicketboxTheme(skin = AppSkin.Default) {
                    CompositionLocalProvider(LocalAppAdaptiveLayoutPolicy provides viewport.value.second) {
                        StatsScreen(state = readableStats, actions = actions(), overview = overview)
                    }
                }
            }
        }
        for (size in listOf(360.dp to AppAdaptiveLayoutPolicy.Compact, 768.dp to medium, 1440.dp to expanded)) {
            composeRule.runOnIdle { viewport.value = size }
            composeRule.onNode(hasText("自定义总览") and hasClickAction()).assertIsDisplayed()
            composeRule.onNodeWithTag("overview-module-recent_uploads").performScrollTo()
            composeRule.onNodeWithText(context.getString(R.string.dashboard_ledger_scope), useUnmergedTree = true)
                .assertIsDisplayed()
            val tab = composeRule.onNode(hasText(context.getString(R.string.stats_tab_overview)) and hasClickAction())
                .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
            val result = composeRule.onNodeWithText(context.getString(R.string.stats_overview_month_spend_label))
                .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
            val filter = composeRule.onNode(hasText(monthLabel) and hasClickAction())
                .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
            assertTrue("Tabs must stay in the result column at ${size.first}", tab.left < result.right && tab.right > result.left)
            assertTrue("Filters precede the views they control", filter.bottom <= tab.top)
            assertTrue("Views precede their results", tab.bottom <= result.top)
        }
    }

    @Test
    fun verticalHingeKeepsBothRealConsumersOutsideTheOccludedArea() {
        var hinge = Rect.Zero
        val editorOpen = mutableStateOf(false)
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(1440.dp, 900.dp))) {
                // FoldingFeature bounds use physical pixels, including under ForcedSize's test density.
                hinge = with(LocalDensity.current) {
                    Rect(700.dp.roundToPx().toFloat(), 0f, 740.dp.roundToPx().toFloat(), 900.dp.roundToPx().toFloat())
                }
                val directive = PaneScaffoldDirective.Default.copy(maxHorizontalPartitions = 2, excludedBounds = listOf(hinge))
                TicketboxTheme(skin = AppSkin.Default) {
                    CompositionLocalProvider(
                        LocalAppAdaptiveLayoutPolicy provides expanded.copy(
                            postureConstraint = AppAdaptivePostureConstraint.VerticalSeparatingOrOccludingHinge,
                        ),
                        LocalAppAdaptivePaneDirective provides directive,
                    ) {
                        StatsScreen(
                            state = readableStats,
                            actions = actions(onEdit = { editorOpen.value = true }),
                            overview = if (editorOpen.value) overview.copy(
                                layout = overview.layout.copy(draft = overview.layout.cards),
                            ) else overview,
                        )
                    }
                }
            }
        }
        val primary = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Insights.primaryTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        val supporting = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Insights.supportingTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        assertTrue("Results must not be under the hinge: primary=$primary, hinge=$hinge", primary.right <= hinge.left)
        assertTrue("Filters must not be under the hinge: supporting=$supporting, hinge=$hinge", supporting.left >= hinge.right)
        composeRule.onNode(hasText(monthLabel) and hasClickAction()).assertIsDisplayed().performClick()
        composeRule.onNodeWithText(context.getString(R.string.components_month_picker_title)).assertIsDisplayed()
        composeRule.onNode(hasText(context.getString(R.string.components_month_picker_all_months)) and hasClickAction())
            .performClick()
        composeRule.onNode(hasText("自定义总览") and hasClickAction()).performClick()
        val editor = composeRule.onNodeWithText(context.getString(R.string.dashboard_editor_title))
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        val save = composeRule.onNode(hasText(context.getString(R.string.dashboard_save)) and hasClickAction())
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        assertTrue("Editor must stay out of the hinge: $editor", editor.right <= hinge.left || editor.left >= hinge.right)
        assertTrue("Save must stay out of the hinge: $save", save.right <= hinge.left || save.left >= hinge.right)
    }

    @Test
    fun compactControlsKeepRetainedTagsMonthFailureAndTabSelectionUsable() {
        var selectedMonth: String? = null
        var selectedTag: String? = null
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(360.dp, 900.dp))) {
                TicketboxTheme(skin = AppSkin.Default) {
                    StatsScreen(
                        state = readableStats.copy(tagsLoadState = StatsFilterOptionsLoadState.Failed),
                        overview = overview,
                        actions = actions(onMonthChange = { selectedMonth = it }, onTagChange = { selectedTag = it }),
                    )
                }
            }
        }
        composeRule.onNode(hasText("#日常") and hasClickAction()).performClick()
        composeRule.onNode(hasText("#旅行") and hasClickAction()).assertIsDisplayed().performClick()
        composeRule.runOnIdle { assertEquals("旅行", selectedTag) }
        composeRule.onNode(hasText(monthLabel) and hasClickAction()).performClick()
        composeRule.onNodeWithText(context.getString(R.string.components_month_picker_failed)).assertIsDisplayed()
        composeRule.onNode(hasText(context.getString(R.string.components_month_picker_all_months)) and hasClickAction())
            .performClick()
        composeRule.runOnIdle { assertEquals("", selectedMonth) }
        composeRule.onNodeWithText(context.getString(R.string.components_month_picker_title)).assertDoesNotExist()
        composeRule.onNode(hasText(context.getString(R.string.stats_tab_trend)) and hasClickAction())
            .performClick().assertIsSelected()
        composeRule.onNode(hasText(context.getString(R.string.stats_tab_category)) and hasClickAction())
            .performClick().assertIsSelected()
    }

    private val monthLabel: String
        get() = context.getString(R.string.components_month_label, "2026", "9")

    private fun actions(
        onMonthChange: (String) -> Unit = {},
        onTagChange: (String) -> Unit = {},
        onEdit: () -> Unit = {},
    ) = StatsScreenActions(
        overview = OverviewInteractionActions(
            DashboardLayoutActions({}, onEdit, { _, _ -> }, { _, _ -> }, {}, {}, {}),
            OverviewModuleActions({}, {}, {}, {}),
        ),
        filters = StatsFilterActions(onMonthChange, onTagChange),
        onRefresh = {},
        onOpenDataQuality = {},
        reports = StatsReportActions(onDrillToLedger = {}, onGranularityChange = {}, onRankingMetricChange = {}),
    )

    private companion object {
        val overview = OverviewModulesState(
            layout = DashboardLayoutUiState(cards = listOf(
                DashboardCard("monthly_spend", "本月支出", true, 0),
                DashboardCard("reports", "趋势报表", true, 1),
                DashboardCard("recent_uploads", "最近上传", true, 2),
            ), canModify = true),
            recurring = RecurringUiState(),
        )
        val readableStats = StatsUiState(
            month = "2026-09",
            stats = MonthlyStats(month = "2026-09", totalAmountCents = 12390, count = 2, byCategory = emptyList()),
            statsSource = StatsSource.Backend,
            monthsLoadState = StatsFilterOptionsLoadState.Failed,
            selectedTag = "日常",
            tags = listOf("日常", "旅行"),
            tagsLoadState = StatsFilterOptionsLoadState.Loaded,
        )
        val expanded = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Expanded,
            paneMode = AppAdaptivePaneMode.ExpandedSupporting,
            primaryNavigation = AppPrimaryNavigationMode.Rail,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
        val medium = expanded.copy(widthClass = AppWindowWidthClass.Medium, paneMode = AppAdaptivePaneMode.MediumSingle)
    }
}
