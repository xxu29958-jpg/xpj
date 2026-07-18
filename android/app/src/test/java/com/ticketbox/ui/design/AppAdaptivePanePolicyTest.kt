package com.ticketbox.ui.design

import androidx.compose.material3.adaptive.HingeInfo
import androidx.compose.material3.adaptive.Posture
import androidx.compose.material3.adaptive.WindowAdaptiveInfo
import androidx.compose.ui.geometry.Rect
import androidx.window.core.layout.WindowSizeClass
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class AppAdaptivePanePolicyTest {
    @Test
    fun compactWindowUsesSinglePaneAndBottomNavigation() {
        val policy = resolveAppAdaptiveLayoutPolicy(windowSizeClass(widthDp = 599f))

        assertEquals(AppWindowWidthClass.Compact, policy.widthClass)
        assertEquals(AppAdaptivePaneMode.CompactSingle, policy.paneMode)
        assertEquals(AppPrimaryNavigationMode.BottomBar, policy.primaryNavigation)
        assertEquals(AppAdaptivePostureConstraint.None, policy.postureConstraint)
        assertFalse(policy.showsSupportingPane)
    }

    @Test
    fun mediumWindowUsesSinglePaneAndNavigationRail() {
        val policy = resolveAppAdaptiveLayoutPolicy(windowSizeClass(widthDp = 600f))

        assertEquals(AppWindowWidthClass.Medium, policy.widthClass)
        assertEquals(AppAdaptivePaneMode.MediumSingle, policy.paneMode)
        assertEquals(AppPrimaryNavigationMode.Rail, policy.primaryNavigation)
        assertFalse(policy.showsSupportingPane)
    }

    @Test
    fun expandedWindowUsesExplicitSupportingPane() {
        val policy = resolveAppAdaptiveLayoutPolicy(windowSizeClass(widthDp = 840f))

        assertEquals(AppWindowWidthClass.Expanded, policy.widthClass)
        assertEquals(AppAdaptivePaneMode.ExpandedSupporting, policy.paneMode)
        assertEquals(AppPrimaryNavigationMode.Rail, policy.primaryNavigation)
        assertTrue(policy.showsSupportingPane)
    }

    @Test
    fun tabletopPostureFallsBackToSinglePaneAndBottomNavigation() {
        val policy = resolveAppAdaptiveLayoutPolicy(
            windowSizeClass = windowSizeClass(widthDp = 840f),
            isTabletop = true,
        )

        assertEquals(AppAdaptivePaneMode.PostureSafeSingle, policy.paneMode)
        assertEquals(AppAdaptivePostureConstraint.Tabletop, policy.postureConstraint)
        assertEquals(AppPrimaryNavigationMode.BottomBar, policy.primaryNavigation)
        assertFalse(policy.showsSupportingPane)
    }

    @Test
    fun verticalHingeUsesOfficialBoundsOnlyWhenExpanded() {
        val separatingWindowInfo = verticalHingeWindowInfo(
            isSeparating = true,
            isOccluding = false,
        )
        val policy = separatingWindowInfo.toAppAdaptiveLayoutPolicy()

        assertEquals(AppAdaptivePaneMode.ExpandedSupporting, policy.paneMode)
        assertEquals(
            AppAdaptivePostureConstraint.VerticalSeparatingOrOccludingHinge,
            policy.postureConstraint,
        )
        assertEquals(AppPrimaryNavigationMode.Rail, policy.primaryNavigation)
        assertTrue(policy.showsSupportingPane)
        assertTrue(policy.usesOfficialVerticalHingeBounds)
        assertEquals(
            listOf(syntheticVerticalHingeBounds),
            assertNotNull(separatingWindowInfo.toAppAdaptivePaneDirective(policy)).excludedBounds,
        )

        val occludingOnlyWindowInfo = verticalHingeWindowInfo(
            isSeparating = false,
            isOccluding = true,
        )
        assertEquals(
            listOf(syntheticVerticalHingeBounds),
            assertNotNull(occludingOnlyWindowInfo.toAppAdaptivePaneDirective()).excludedBounds,
        )

        val mediumPolicy = resolveAppAdaptiveLayoutPolicy(
            windowSizeClass = windowSizeClass(widthDp = 600f),
            hasVerticalSeparatingOrOccludingHinge = true,
        )
        assertEquals(AppAdaptivePaneMode.PostureSafeSingle, mediumPolicy.paneMode)
        assertFalse(mediumPolicy.usesOfficialVerticalHingeBounds)

        val horizontalPolicy = resolveAppAdaptiveLayoutPolicy(
            windowSizeClass = windowSizeClass(widthDp = 840f),
            hasHorizontalSeparatingOrOccludingHinge = true,
        )
        assertEquals(AppAdaptivePaneMode.PostureSafeSingle, horizontalPolicy.paneMode)
        assertEquals(
            AppAdaptivePostureConstraint.HorizontalSeparatingOrOccludingHinge,
            horizontalPolicy.postureConstraint,
        )
        assertFalse(horizontalPolicy.showsSupportingPane)
    }

    @Test
    fun postureSafeSingleExposesMediumVerticalAndTabletopHingeBounds() {
        val mediumVerticalBounds = Rect(
            left = 300f,
            top = 0f,
            right = 300f,
            bottom = syntheticWindowHeight,
        )
        val mediumVerticalInfo = hingeWindowInfo(
            widthDp = 600f,
            bounds = mediumVerticalBounds,
            isVertical = true,
        )
        val mediumPolicy = mediumVerticalInfo.toAppAdaptiveLayoutPolicy()

        assertEquals(AppAdaptivePaneMode.PostureSafeSingle, mediumPolicy.paneMode)
        assertTrue(mediumPolicy.usesPostureSafeBounds)
        assertEquals(
            listOf(AppPostureSafeHingeBounds(mediumVerticalBounds, isVertical = true)),
            mediumVerticalInfo.toAppPostureSafeHingeBounds(mediumPolicy),
        )
        assertEquals(null, mediumVerticalInfo.toAppAdaptivePaneDirective(mediumPolicy))

        val horizontalBounds = Rect(
            left = 0f,
            top = syntheticWindowHeight / 2,
            right = syntheticWindowWidth,
            bottom = syntheticWindowHeight / 2,
        )
        val tabletopInfo = hingeWindowInfo(
            widthDp = syntheticWindowWidth,
            bounds = horizontalBounds,
            isVertical = false,
        )
        val tabletopPolicy = tabletopInfo.toAppAdaptiveLayoutPolicy()

        assertEquals(AppAdaptivePaneMode.PostureSafeSingle, tabletopPolicy.paneMode)
        assertTrue(tabletopPolicy.usesPostureSafeBounds)
        assertEquals(
            listOf(AppPostureSafeHingeBounds(horizontalBounds, isVertical = false)),
            tabletopInfo.toAppPostureSafeHingeBounds(tabletopPolicy),
        )
        assertEquals(null, tabletopInfo.toAppAdaptivePaneDirective(tabletopPolicy))
    }

    @Test
    fun expandedSupportingWidthPreservesBothPaneMinimums() {
        val expandedBoundaryWidth = AppAdaptiveBreakpoints.expandedWidthMin
        val supportingWidth = appAdaptiveSupportingPaneWidth(expandedBoundaryWidth)
        val primaryWidth = expandedBoundaryWidth -
            AppAdaptivePaneTokens.paneGutter -
            AppAdaptivePaneTokens.paneGutter -
            supportingWidth

        assertEquals(AppAdaptivePaneTokens.supportingMinWidth, supportingWidth)
        assertTrue(primaryWidth >= AppAdaptivePaneTokens.primaryMinWidth)
        assertTrue(supportingWidth <= AppAdaptivePaneTokens.supportingMaxWidth)
    }

    private fun windowSizeClass(widthDp: Float): WindowSizeClass =
        WindowSizeClass.compute(dpWidth = widthDp, dpHeight = 900f)

    private fun verticalHingeWindowInfo(
        isSeparating: Boolean,
        isOccluding: Boolean,
    ): WindowAdaptiveInfo = hingeWindowInfo(
        widthDp = syntheticWindowWidth,
        bounds = syntheticVerticalHingeBounds,
        isVertical = true,
        isSeparating = isSeparating,
        isOccluding = isOccluding,
    )

    private fun hingeWindowInfo(
        widthDp: Float,
        bounds: Rect,
        isVertical: Boolean,
        isSeparating: Boolean = true,
        isOccluding: Boolean = true,
    ): WindowAdaptiveInfo = WindowAdaptiveInfo(
        windowSizeClass = windowSizeClass(widthDp = widthDp),
        windowPosture = Posture(
            hingeList = listOf(
                HingeInfo(
                    bounds = bounds,
                    isFlat = false,
                    isVertical = isVertical,
                    isSeparating = isSeparating,
                    isOccluding = isOccluding,
                ),
            ),
        ),
    )

    private companion object {
        const val syntheticWindowWidth = 840f
        const val syntheticWindowHeight = 900f
        val syntheticVerticalHingeBounds = Rect(
            left = syntheticWindowWidth / 2,
            top = 0f,
            right = syntheticWindowWidth / 2,
            bottom = syntheticWindowHeight,
        )
    }
}
