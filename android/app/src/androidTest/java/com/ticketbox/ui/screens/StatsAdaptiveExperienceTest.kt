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
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
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
                        StatsScreen(state = readableStats, actions = actions())
                    }
                }
            }
        }
        for (size in listOf(360.dp to AppAdaptiveLayoutPolicy.Compact, 768.dp to medium, 1440.dp to expanded)) {
            composeRule.runOnIdle { viewport.value = size }
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
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(1440.dp, 900.dp))) {
                hinge = with(LocalDensity.current) { Rect(700.dp.toPx(), 0f, 740.dp.toPx(), 900.dp.toPx()) }
                val directive = PaneScaffoldDirective.Default.copy(maxHorizontalPartitions = 2, excludedBounds = listOf(hinge))
                TicketboxTheme(skin = AppSkin.Default) {
                    CompositionLocalProvider(
                        LocalAppAdaptiveLayoutPolicy provides expanded.copy(
                            postureConstraint = AppAdaptivePostureConstraint.VerticalSeparatingOrOccludingHinge,
                        ),
                        LocalAppAdaptivePaneDirective provides directive,
                    ) {
                        StatsScreen(state = readableStats, actions = actions())
                    }
                }
            }
        }
        val primary = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Insights.primaryTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        val supporting = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Insights.supportingTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        assertTrue("Results must not be under the hinge", primary.right <= hinge.left)
        assertTrue("Filters must not be under the hinge", supporting.left >= hinge.right)
        composeRule.onNode(hasText(monthLabel) and hasClickAction()).assertIsDisplayed().performClick()
        composeRule.onNodeWithText(context.getString(R.string.components_month_picker_title)).assertIsDisplayed()
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
    ) = StatsScreenActions(
        filters = StatsFilterActions(onMonthChange, onTagChange),
        onRefresh = {},
        onOpenDataQuality = {},
        reports = StatsReportActions(onDrillToLedger = {}, onGranularityChange = {}, onRankingMetricChange = {}),
    )

    private companion object {
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
