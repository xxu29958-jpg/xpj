package com.ticketbox.ui.components

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.adaptive.HingeInfo
import androidx.compose.material3.adaptive.Posture
import androidx.compose.material3.adaptive.WindowAdaptiveInfo
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.isSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Density
import androidx.window.core.layout.WindowSizeClass
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAdaptivePaneMode
import com.ticketbox.ui.design.AppAdaptivePaneTokens
import com.ticketbox.ui.design.AppAdaptivePostureConstraint
import com.ticketbox.ui.design.AppPrimaryNavigationMode
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.toAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.toAppAdaptivePaneDirective
import com.ticketbox.ui.design.toAppPostureSafeHingeBounds
import com.ticketbox.ui.navigation.PrimaryDomain
import com.ticketbox.ui.navigation.toPrimaryNavItem
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AppAdaptivePaneConsumersTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun allProductDomainsRenderPrimaryOnlyUnderMediumPolicy() {
        assertAllPaneStructures(
            policy = mediumPolicy,
            supportingPaneExpected = false,
        )
    }

    @Test
    fun allProductDomainsRenderPrimaryAndSupportingUnderExpandedPolicy() {
        assertAllPaneStructures(
            policy = expandedPolicy,
            supportingPaneExpected = true,
        )
    }

    @Test
    fun expandedVerticalHingeKeepsEveryDomainInOfficialPhysicalPartitions() {
        var activeDomain by mutableStateOf(AppAdaptiveProductDomain.entries.first())
        var excludedHingeBounds = Rect.Zero
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ExpandedVerticalHingeViewport { windowAdaptiveInfo ->
                    val policy = windowAdaptiveInfo.toAppAdaptiveLayoutPolicy()
                    val directive = checkNotNull(
                        windowAdaptiveInfo.toAppAdaptivePaneDirective(policy),
                    )
                    excludedHingeBounds = directive.excludedBounds.single()
                    CompositionLocalProvider(
                        LocalAppAdaptivePaneDirective provides directive,
                        LocalAppAdaptiveLayoutPolicy provides policy,
                    ) {
                        AppAdaptiveRealProductConsumer(
                            domain = activeDomain,
                        )
                    }
                }
            }
        }

        AppAdaptivePaneStructures.All.forEach { structure ->
            composeRule.runOnIdle { activeDomain = structure.domain }
            val primaryPane = composeRule.onNodeWithTag(structure.primaryTestTag)
                .assertIsDisplayed()
            val supportingPane = composeRule.onNodeWithTag(structure.supportingTestTag)
                .assertIsDisplayed()

            assertTrue(
                primaryPane.fetchSemanticsNode().boundsInRoot.right <= excludedHingeBounds.left,
            )
            assertTrue(
                supportingPane.fetchSemanticsNode().boundsInRoot.left >= excludedHingeBounds.right,
            )
        }
    }

    @Test
    fun postureSafeSingleKeepsMediumBookAndTabletopContentOutsideFoldBounds() {
        var scenario by mutableStateOf(PostureSafeScenario.MediumBook)
        var excludedHingeBounds = Rect.Zero
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                PostureSafeHingeViewport(scenario) { windowAdaptiveInfo ->
                    val policy = windowAdaptiveInfo.toAppAdaptiveLayoutPolicy()
                    val excludedBounds = windowAdaptiveInfo.toAppPostureSafeHingeBounds(policy)
                    excludedHingeBounds = excludedBounds.single().bounds
                    AppPostureSafeContent(excludedBounds = excludedBounds) {
                        CompositionLocalProvider(LocalAppAdaptiveLayoutPolicy provides policy) {
                            AppAdaptiveRealProductConsumer(domain = AppAdaptiveProductDomain.Inbox)
                        }
                    }
                }
            }
        }

        PostureSafeScenario.entries.forEach { targetScenario ->
            composeRule.runOnIdle { scenario = targetScenario }
            composeRule.waitForIdle()
            val primaryBounds = composeRule
                .onNodeWithTag(AppAdaptivePaneStructures.Inbox.primaryTestTag)
                .assertIsDisplayed()
                .fetchSemanticsNode()
                .boundsInRoot
            val staysOutsideFold = if (targetScenario.isVertical) {
                primaryBounds.right <= excludedHingeBounds.left ||
                    primaryBounds.left >= excludedHingeBounds.right
            } else {
                primaryBounds.bottom <= excludedHingeBounds.top ||
                    primaryBounds.top >= excludedHingeBounds.bottom
            }

            assertTrue(staysOutsideFold)
            composeRule
                .onNodeWithTag(AppAdaptivePaneStructures.Inbox.supportingTestTag)
                .assertDoesNotExist()
        }
    }

    @Test
    fun navigationRailExposesFiveDomainsAndExactlyOneSelectedDestination() {
        var selectedKey by mutableStateOf(PrimaryDomain.Plans.key)
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppNavigationRail(
                    items = PrimaryDomain.entries.map { it.toPrimaryNavItem() },
                    selectedKey = selectedKey,
                    onSelect = { selectedKey = it.key },
                )
            }
        }

        railLabels.forEach { label ->
            composeRule.onNode(railItemMatcher(label), useUnmergedTree = true)
                .assertExists()
                .assert(hasClickAction())
        }
        assertExactlyOneSelected("计划")

        composeRule.onNode(railItemMatcher("洞察"), useUnmergedTree = true).performClick()
        composeRule.waitForIdle()

        assertEquals(PrimaryDomain.Insights.key, selectedKey)
        assertExactlyOneSelected("洞察")
    }

    private fun assertAllPaneStructures(
        policy: AppAdaptiveLayoutPolicy,
        supportingPaneExpected: Boolean,
    ) {
        var activeDomain by mutableStateOf(AppAdaptiveProductDomain.entries.first())
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ExpandedWidthTestViewport {
                    CompositionLocalProvider(LocalAppAdaptiveLayoutPolicy provides policy) {
                        AppAdaptiveRealProductConsumer(domain = activeDomain)
                    }
                }
            }
        }

        AppAdaptivePaneStructures.All.forEach { structure ->
            composeRule.runOnIdle { activeDomain = structure.domain }
            composeRule.onNodeWithTag(structure.primaryTestTag).assertIsDisplayed()
            val supportingPane = composeRule.onNodeWithTag(structure.supportingTestTag)
            if (supportingPaneExpected) {
                supportingPane.assertIsDisplayed()
            } else {
                supportingPane.assertDoesNotExist()
            }
        }
    }

    private fun assertExactlyOneSelected(label: String) {
        composeRule.onAllNodes(isSelected(), useUnmergedTree = true).assertCountEquals(1)
        composeRule.onNode(
            railItemMatcher(label) and isSelected(),
            useUnmergedTree = true,
        ).assertExists()
    }

    private fun railItemMatcher(label: String): SemanticsMatcher =
        hasClickAction() and hasAnyDescendant(hasContentDescription(label))

    @Composable
    private fun ExpandedWidthTestViewport(content: @Composable () -> Unit) {
        BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
            val sourceDensity = LocalDensity.current
            val viewportWidthPx = with(sourceDensity) { maxWidth.toPx() }
            val expandedDensity = Density(
                density = viewportWidthPx / AppAdaptivePaneTokens.maxContentWidth.value,
                fontScale = sourceDensity.fontScale,
            )
            CompositionLocalProvider(LocalDensity provides expandedDensity) {
                content()
            }
        }
    }

    @Composable
    private fun ExpandedVerticalHingeViewport(
        content: @Composable (WindowAdaptiveInfo) -> Unit,
    ) {
        BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
            val sourceDensity = LocalDensity.current
            val viewportWidthPx = with(sourceDensity) { maxWidth.toPx() }
            val viewportHeightPx = with(sourceDensity) { maxHeight.toPx() }
            val expandedDensity = Density(
                density = viewportWidthPx / AppAdaptivePaneTokens.maxContentWidth.value,
                fontScale = sourceDensity.fontScale,
            )
            val hingeBounds = Rect(
                left = viewportWidthPx / 2,
                top = 0f,
                right = viewportWidthPx / 2,
                bottom = viewportHeightPx,
            )
            val windowAdaptiveInfo = WindowAdaptiveInfo(
                windowSizeClass = WindowSizeClass.compute(
                    dpWidth = AppAdaptivePaneTokens.maxContentWidth.value,
                    dpHeight = viewportHeightPx / expandedDensity.density,
                ),
                windowPosture = Posture(
                    hingeList = listOf(
                        HingeInfo(
                            bounds = hingeBounds,
                            isFlat = false,
                            isVertical = true,
                            isSeparating = true,
                            isOccluding = true,
                        ),
                    ),
                ),
            )
            CompositionLocalProvider(LocalDensity provides expandedDensity) {
                content(windowAdaptiveInfo)
            }
        }
    }

    @Composable
    private fun PostureSafeHingeViewport(
        scenario: PostureSafeScenario,
        content: @Composable (WindowAdaptiveInfo) -> Unit,
    ) {
        BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
            val sourceDensity = LocalDensity.current
            val viewportWidthPx = with(sourceDensity) { maxWidth.toPx() }
            val viewportHeightPx = with(sourceDensity) { maxHeight.toPx() }
            val widthDp = scenario.widthDp
            val testDensity = Density(
                density = viewportWidthPx / widthDp,
                fontScale = sourceDensity.fontScale,
            )
            val hingeHalfThicknessPx =
                POSTURE_SAFE_HINGE_HALF_THICKNESS_DP * testDensity.density
            val hingeBounds = if (scenario.isVertical) {
                Rect(
                    left = viewportWidthPx / 2 - hingeHalfThicknessPx,
                    top = 0f,
                    right = viewportWidthPx / 2 + hingeHalfThicknessPx,
                    bottom = viewportHeightPx,
                )
            } else {
                Rect(
                    left = 0f,
                    top = viewportHeightPx / 2 - hingeHalfThicknessPx,
                    right = viewportWidthPx,
                    bottom = viewportHeightPx / 2 + hingeHalfThicknessPx,
                )
            }
            val windowAdaptiveInfo = WindowAdaptiveInfo(
                windowSizeClass = WindowSizeClass.compute(
                    dpWidth = widthDp,
                    dpHeight = viewportHeightPx / testDensity.density,
                ),
                windowPosture = Posture(
                    hingeList = listOf(
                        HingeInfo(
                            bounds = hingeBounds,
                            isFlat = false,
                            isVertical = scenario.isVertical,
                            isSeparating = true,
                            isOccluding = true,
                        ),
                    ),
                ),
            )
            CompositionLocalProvider(LocalDensity provides testDensity) {
                content(windowAdaptiveInfo)
            }
        }
    }

    private companion object {
        val mediumPolicy = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Medium,
            paneMode = AppAdaptivePaneMode.MediumSingle,
            primaryNavigation = AppPrimaryNavigationMode.Rail,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
        val expandedPolicy = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Expanded,
            paneMode = AppAdaptivePaneMode.ExpandedSupporting,
            primaryNavigation = AppPrimaryNavigationMode.Rail,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
        val railLabels = listOf("收件", "流水", "往来", "计划", "洞察")
        const val POSTURE_SAFE_HINGE_HALF_THICKNESS_DP = 4f
    }
}

private enum class PostureSafeScenario(
    val widthDp: Float,
    val isVertical: Boolean,
) {
    MediumBook(widthDp = 600f, isVertical = true),
    Tabletop(widthDp = AppAdaptivePaneTokens.maxContentWidth.value, isVertical = false),
}
