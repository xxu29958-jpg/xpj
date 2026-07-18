package com.ticketbox.ui.design

import androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi
import androidx.compose.material3.adaptive.WindowAdaptiveInfo
import androidx.compose.material3.adaptive.layout.HingePolicy
import androidx.compose.material3.adaptive.layout.PaneScaffoldDirective
import androidx.compose.material3.adaptive.layout.calculatePaneScaffoldDirective
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.window.core.layout.WindowSizeClass
import androidx.window.core.layout.WindowSizeClass.Companion.WIDTH_DP_EXPANDED_LOWER_BOUND
import androidx.window.core.layout.WindowSizeClass.Companion.WIDTH_DP_MEDIUM_LOWER_BOUND

enum class AppWindowWidthClass {
    Compact,
    Medium,
    Expanded,
}

enum class AppAdaptivePaneMode {
    CompactSingle,
    MediumSingle,
    ExpandedSupporting,
    PostureSafeSingle,
}

enum class AppPrimaryNavigationMode {
    BottomBar,
    Rail,
}

enum class AppAdaptivePostureConstraint {
    None,
    Tabletop,
    HorizontalSeparatingOrOccludingHinge,
    VerticalSeparatingOrOccludingHinge,
}

@Immutable
data class AppAdaptiveLayoutPolicy(
    val widthClass: AppWindowWidthClass,
    val paneMode: AppAdaptivePaneMode,
    val primaryNavigation: AppPrimaryNavigationMode,
    val postureConstraint: AppAdaptivePostureConstraint,
) {
    val showsSupportingPane: Boolean
        get() = paneMode == AppAdaptivePaneMode.ExpandedSupporting

    val usesOfficialVerticalHingeBounds: Boolean
        get() = showsSupportingPane &&
            postureConstraint == AppAdaptivePostureConstraint.VerticalSeparatingOrOccludingHinge

    val usesPostureSafeBounds: Boolean
        get() = paneMode == AppAdaptivePaneMode.PostureSafeSingle

    companion object {
        val Compact = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Compact,
            paneMode = AppAdaptivePaneMode.CompactSingle,
            primaryNavigation = AppPrimaryNavigationMode.BottomBar,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
    }
}

@Immutable
data class AppPostureSafeHingeBounds(
    val bounds: Rect,
    val isVertical: Boolean,
)

object AppAdaptivePaneTokens {
    val maxContentWidth: Dp = AppAdaptiveBreakpoints.twoPaneContentMaxWidth
    val primaryMinWidth: Dp = 440.dp
    val supportingMinWidth: Dp = 280.dp
    val supportingMaxWidth: Dp = 360.dp
    val paneGutter: Dp = AppSpacing.smallGap
    const val supportingPreferredFraction: Float = 0.30f
}

val LocalAppAdaptiveLayoutPolicy = staticCompositionLocalOf {
    AppAdaptiveLayoutPolicy.Compact
}

fun resolveAppAdaptiveLayoutPolicy(
    windowSizeClass: WindowSizeClass,
    isTabletop: Boolean = false,
    hasVerticalSeparatingOrOccludingHinge: Boolean = false,
    hasHorizontalSeparatingOrOccludingHinge: Boolean = false,
): AppAdaptiveLayoutPolicy {
    val widthClass = windowSizeClass.toAppWindowWidthClass()
    val postureConstraint = resolveAppAdaptivePostureConstraint(
        isTabletop = isTabletop,
        hasVerticalHinge = hasVerticalSeparatingOrOccludingHinge,
        hasHorizontalHinge = hasHorizontalSeparatingOrOccludingHinge,
    )
    return AppAdaptiveLayoutPolicy(
        widthClass = widthClass,
        paneMode = resolveAppAdaptivePaneMode(widthClass, postureConstraint),
        primaryNavigation = resolveAppPrimaryNavigation(widthClass, postureConstraint),
        postureConstraint = postureConstraint,
    )
}

private fun WindowSizeClass.toAppWindowWidthClass(): AppWindowWidthClass = when {
    isWidthAtLeastBreakpoint(WIDTH_DP_EXPANDED_LOWER_BOUND) -> AppWindowWidthClass.Expanded
    isWidthAtLeastBreakpoint(WIDTH_DP_MEDIUM_LOWER_BOUND) -> AppWindowWidthClass.Medium
    else -> AppWindowWidthClass.Compact
}

private fun resolveAppAdaptivePostureConstraint(
    isTabletop: Boolean,
    hasVerticalHinge: Boolean,
    hasHorizontalHinge: Boolean,
): AppAdaptivePostureConstraint = when {
    isTabletop -> AppAdaptivePostureConstraint.Tabletop
    hasHorizontalHinge -> AppAdaptivePostureConstraint.HorizontalSeparatingOrOccludingHinge
    hasVerticalHinge -> AppAdaptivePostureConstraint.VerticalSeparatingOrOccludingHinge
    else -> AppAdaptivePostureConstraint.None
}

private fun resolveAppAdaptivePaneMode(
    widthClass: AppWindowWidthClass,
    postureConstraint: AppAdaptivePostureConstraint,
): AppAdaptivePaneMode = when {
    postureConstraint == AppAdaptivePostureConstraint.Tabletop ->
        AppAdaptivePaneMode.PostureSafeSingle
    postureConstraint == AppAdaptivePostureConstraint.HorizontalSeparatingOrOccludingHinge ->
        AppAdaptivePaneMode.PostureSafeSingle
    postureConstraint == AppAdaptivePostureConstraint.VerticalSeparatingOrOccludingHinge &&
        widthClass != AppWindowWidthClass.Expanded ->
        AppAdaptivePaneMode.PostureSafeSingle
    widthClass == AppWindowWidthClass.Expanded -> AppAdaptivePaneMode.ExpandedSupporting
    widthClass == AppWindowWidthClass.Medium -> AppAdaptivePaneMode.MediumSingle
    else -> AppAdaptivePaneMode.CompactSingle
}

private fun resolveAppPrimaryNavigation(
    widthClass: AppWindowWidthClass,
    postureConstraint: AppAdaptivePostureConstraint,
): AppPrimaryNavigationMode =
    if (
        widthClass == AppWindowWidthClass.Compact ||
        postureConstraint == AppAdaptivePostureConstraint.Tabletop
    ) {
        AppPrimaryNavigationMode.BottomBar
    } else {
        AppPrimaryNavigationMode.Rail
    }

fun WindowAdaptiveInfo.toAppAdaptiveLayoutPolicy(): AppAdaptiveLayoutPolicy =
    resolveAppAdaptiveLayoutPolicy(
        windowSizeClass = windowSizeClass,
        isTabletop = windowPosture.isTabletop,
        hasVerticalSeparatingOrOccludingHinge = windowPosture.hingeList.any {
            it.isVertical && (it.isSeparating || it.isOccluding)
        },
        hasHorizontalSeparatingOrOccludingHinge = windowPosture.hingeList.any {
            !it.isVertical && (it.isSeparating || it.isOccluding)
        },
    )

fun WindowAdaptiveInfo.toAppPostureSafeHingeBounds(
    policy: AppAdaptiveLayoutPolicy = toAppAdaptiveLayoutPolicy(),
): List<AppPostureSafeHingeBounds> {
    if (!policy.usesPostureSafeBounds) {
        return emptyList()
    }
    return windowPosture.hingeList
        .filter { it.isSeparating || it.isOccluding }
        .map { hinge ->
            AppPostureSafeHingeBounds(
                bounds = hinge.bounds,
                isVertical = hinge.isVertical,
            )
        }
}

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
fun WindowAdaptiveInfo.toAppAdaptivePaneDirective(
    policy: AppAdaptiveLayoutPolicy = toAppAdaptiveLayoutPolicy(),
): PaneScaffoldDirective? {
    if (!policy.usesOfficialVerticalHingeBounds) {
        return null
    }
    return calculatePaneScaffoldDirective(
        windowAdaptiveInfo = this,
        verticalHingePolicy = HingePolicy.AlwaysAvoid,
    ).takeIf {
        it.excludedBounds.isNotEmpty()
    }
}

fun appAdaptiveSupportingPaneWidth(maxWidth: Dp): Dp {
    val boundedWidth = minOf(maxWidth, AppAdaptivePaneTokens.maxContentWidth)
    val totalGutter = AppAdaptivePaneTokens.paneGutter + AppAdaptivePaneTokens.paneGutter
    val usableWidth = (boundedWidth - totalGutter).coerceAtLeast(AppSpacing.none)
    val maxByPrimary = (usableWidth - AppAdaptivePaneTokens.primaryMinWidth)
        .coerceAtLeast(AppSpacing.none)
    val upperBound = minOf(
        AppAdaptivePaneTokens.supportingMaxWidth,
        usableWidth / 2,
        maxByPrimary,
    )
    val lowerBound = minOf(AppAdaptivePaneTokens.supportingMinWidth, upperBound)
    return (usableWidth * AppAdaptivePaneTokens.supportingPreferredFraction)
        .coerceIn(lowerBound, upperBound)
}
