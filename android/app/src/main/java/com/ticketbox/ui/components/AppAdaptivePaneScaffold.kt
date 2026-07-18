package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.VerticalDivider
import androidx.compose.material3.adaptive.ExperimentalMaterial3AdaptiveApi
import androidx.compose.material3.adaptive.layout.PaneAdaptedValue
import androidx.compose.material3.adaptive.layout.PaneScaffoldDirective
import androidx.compose.material3.adaptive.layout.SupportingPaneScaffold
import androidx.compose.material3.adaptive.layout.ThreePaneScaffoldValue
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.Constraints
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAdaptivePaneTokens
import com.ticketbox.ui.design.AppPostureSafeHingeBounds
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.appAdaptiveSupportingPaneWidth
import kotlin.math.ceil
import kotlin.math.floor

enum class AppAdaptiveProductDomain(val key: String) {
    Inbox("inbox"),
    Transactions("transactions"),
    Obligations("obligations"),
    Plans("plans"),
    Insights("insights"),
}

enum class AppAdaptivePanePurpose {
    ReviewQueue,
    IntakeAndTriage,
    TransactionRegister,
    RegisterControls,
    ObligationList,
    ObligationNavigation,
    PlanOverview,
    FixedArrangements,
    InsightResults,
    InsightControls,
}

@Immutable
data class AppAdaptivePaneStructure(
    val domain: AppAdaptiveProductDomain,
    val primaryPurpose: AppAdaptivePanePurpose,
    val supportingPurpose: AppAdaptivePanePurpose,
) {
    val primaryTestTag: String
        get() = "adaptive_${domain.key}_primary"

    val supportingTestTag: String
        get() = "adaptive_${domain.key}_supporting"
}

class AppAdaptiveSupportingPaneContent internal constructor(
    val purpose: AppAdaptivePanePurpose,
    val content: @Composable () -> Unit,
)

fun appAdaptiveSupportingPaneContent(
    purpose: AppAdaptivePanePurpose,
    content: @Composable () -> Unit,
): AppAdaptiveSupportingPaneContent = AppAdaptiveSupportingPaneContent(
    purpose = purpose,
    content = content,
)

object AppAdaptivePaneStructures {
    val Inbox = AppAdaptivePaneStructure(
        domain = AppAdaptiveProductDomain.Inbox,
        primaryPurpose = AppAdaptivePanePurpose.ReviewQueue,
        supportingPurpose = AppAdaptivePanePurpose.IntakeAndTriage,
    )
    val Transactions = AppAdaptivePaneStructure(
        domain = AppAdaptiveProductDomain.Transactions,
        primaryPurpose = AppAdaptivePanePurpose.TransactionRegister,
        supportingPurpose = AppAdaptivePanePurpose.RegisterControls,
    )
    val Obligations = AppAdaptivePaneStructure(
        domain = AppAdaptiveProductDomain.Obligations,
        primaryPurpose = AppAdaptivePanePurpose.ObligationList,
        supportingPurpose = AppAdaptivePanePurpose.ObligationNavigation,
    )
    val Plans = AppAdaptivePaneStructure(
        domain = AppAdaptiveProductDomain.Plans,
        primaryPurpose = AppAdaptivePanePurpose.PlanOverview,
        supportingPurpose = AppAdaptivePanePurpose.FixedArrangements,
    )
    val Insights = AppAdaptivePaneStructure(
        domain = AppAdaptiveProductDomain.Insights,
        primaryPurpose = AppAdaptivePanePurpose.InsightResults,
        supportingPurpose = AppAdaptivePanePurpose.InsightControls,
    )
    val All: List<AppAdaptivePaneStructure> = listOf(
        Inbox,
        Transactions,
        Obligations,
        Plans,
        Insights,
    )
}

val LocalAppAdaptivePaneDirective = staticCompositionLocalOf<PaneScaffoldDirective?> {
    null
}

/**
 * Keeps the complete single-pane product shell inside one physical display
 * region when a separating or occluding fold makes the window discontinuous.
 *
 * This intentionally remains one pane: it chooses the largest safe region
 * around the reported fold bounds instead of turning tabletop or medium book
 * posture into a second product pane.
 */
@Composable
fun AppPostureSafeContent(
    excludedBounds: List<AppPostureSafeHingeBounds>,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Layout(
        content = {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clipToBounds(),
            ) {
                content()
            }
        },
        modifier = modifier.fillMaxSize(),
    ) { measurables, constraints ->
        val layoutWidth = constraints.maxWidth
        val layoutHeight = constraints.maxHeight
        val safeRegion = appPostureSafeRegion(
            width = layoutWidth,
            height = layoutHeight,
            excludedBounds = excludedBounds,
        )
        val placeable = measurables.single().measure(
            Constraints.fixed(
                width = safeRegion.width,
                height = safeRegion.height,
            ),
        )
        layout(layoutWidth, layoutHeight) {
            placeable.place(safeRegion.left, safeRegion.top)
        }
    }
}

@Composable
fun AppAdaptivePaneScaffold(
    structure: AppAdaptivePaneStructure,
    modifier: Modifier = Modifier,
    policy: AppAdaptiveLayoutPolicy = LocalAppAdaptiveLayoutPolicy.current,
    primaryPane: @Composable () -> Unit,
    supportingPane: AppAdaptiveSupportingPaneContent,
) {
    require(supportingPane.purpose == structure.supportingPurpose) { "Mismatched supporting pane purpose" }
    if (policy.usesOfficialVerticalHingeBounds) {
        AppAdaptiveVerticalHingePane(
            structure = structure,
            modifier = modifier,
            primaryPane = primaryPane,
            supportingPane = supportingPane.content,
        )
        return
    }

    if (!policy.showsSupportingPane) {
        AppAdaptiveSinglePane(
            structure = structure,
            modifier = modifier,
            primaryPane = primaryPane,
        )
        return
    }

    BoxWithConstraints(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.TopCenter,
    ) {
        val supportingWidth = appAdaptiveSupportingPaneWidth(maxWidth)
        Row(
            modifier = Modifier
                .widthIn(max = AppAdaptivePaneTokens.maxContentWidth)
                .fillMaxSize(),
        ) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .testTag(structure.primaryTestTag),
            ) {
                primaryPane()
            }
            Spacer(modifier = Modifier.width(AppAdaptivePaneTokens.paneGutter))
            VerticalDivider(modifier = Modifier.fillMaxHeight())
            Spacer(modifier = Modifier.width(AppAdaptivePaneTokens.paneGutter))
            Box(
                modifier = Modifier
                    .width(supportingWidth)
                    .fillMaxHeight()
                    .testTag(structure.supportingTestTag),
            ) {
                supportingPane.content()
            }
        }
    }
}

@Composable
private fun AppAdaptiveVerticalHingePane(
    structure: AppAdaptivePaneStructure,
    modifier: Modifier,
    primaryPane: @Composable () -> Unit,
    supportingPane: @Composable () -> Unit,
) {
    val directive = LocalAppAdaptivePaneDirective.current
    if (directive != null) {
        OfficialVerticalHingePaneScaffold(
            structure = structure,
            directive = directive,
            modifier = modifier,
            primaryPane = primaryPane,
            supportingPane = supportingPane,
        )
    } else {
        AppAdaptiveSinglePane(
            structure = structure,
            modifier = modifier,
            primaryPane = primaryPane,
        )
    }
}

@Composable
private fun AppAdaptiveSinglePane(
    structure: AppAdaptivePaneStructure,
    modifier: Modifier,
    primaryPane: @Composable () -> Unit,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .testTag(structure.primaryTestTag),
    ) {
        primaryPane()
    }
}

@OptIn(ExperimentalMaterial3AdaptiveApi::class)
@Composable
private fun OfficialVerticalHingePaneScaffold(
    structure: AppAdaptivePaneStructure,
    directive: PaneScaffoldDirective,
    modifier: Modifier,
    primaryPane: @Composable () -> Unit,
    supportingPane: @Composable () -> Unit,
) {
    SupportingPaneScaffold(
        directive = directive,
        value = ThreePaneScaffoldValue(
            primary = PaneAdaptedValue.Expanded,
            secondary = PaneAdaptedValue.Expanded,
            tertiary = PaneAdaptedValue.Hidden,
        ),
        modifier = modifier,
        mainPane = {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .testTag(structure.primaryTestTag),
            ) {
                primaryPane()
            }
        },
        supportingPane = {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .testTag(structure.supportingTestTag),
            ) {
                supportingPane()
            }
        },
    )
}

@Composable
fun AppAdaptiveSupportingPane(
    role: AppPageRole,
    modifier: Modifier = Modifier,
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(AppSpacing.cardGap),
    content: @Composable ColumnScope.(AppPageLayoutValues) -> Unit,
) {
    AppPageScrollableColumn(
        chrome = AppScrollablePageChrome(
            page = AppPageChrome(
                role = role,
                hasBottomBar = false,
                horizontalPadding = AppSpacing.cardPaddingSmall,
            ),
            verticalArrangement = verticalArrangement,
        ),
        modifier = modifier,
        content = content,
    )
}

private data class AppPostureSafeRegion(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
) {
    val width: Int
        get() = right - left

    val height: Int
        get() = bottom - top

    val area: Long
        get() = width.toLong() * height
}

private fun appPostureSafeRegion(
    width: Int,
    height: Int,
    excludedBounds: List<AppPostureSafeHingeBounds>,
): AppPostureSafeRegion {
    val fullRegion = AppPostureSafeRegion(
        left = 0,
        top = 0,
        right = width,
        bottom = height,
    )
    val candidates = excludedBounds.fold(listOf(fullRegion)) { regions, hinge ->
        regions.flatMap { region -> region.splitAround(hinge) }
    }
    return candidates.maxByOrNull(AppPostureSafeRegion::area)
        ?: AppPostureSafeRegion(left = 0, top = 0, right = 0, bottom = 0)
}

private fun AppPostureSafeRegion.splitAround(
    hinge: AppPostureSafeHingeBounds,
): List<AppPostureSafeRegion> {
    val bounds = hinge.bounds
    return if (hinge.isVertical) {
        val crossesRegion = bounds.bottom > top && bounds.top < bottom
        val excludedStart = floor(bounds.left).toInt().coerceIn(left, right)
        val excludedEnd = ceil(bounds.right).toInt().coerceIn(left, right)
        if (!crossesRegion || excludedStart >= right || excludedEnd <= left) {
            listOf(this)
        } else {
            buildList {
                if (excludedStart > left) {
                    add(copy(right = excludedStart))
                }
                if (excludedEnd < right) {
                    add(copy(left = excludedEnd))
                }
            }
        }
    } else {
        val crossesRegion = bounds.right > left && bounds.left < right
        val excludedStart = floor(bounds.top).toInt().coerceIn(top, bottom)
        val excludedEnd = ceil(bounds.bottom).toInt().coerceIn(top, bottom)
        if (!crossesRegion || excludedStart >= bottom || excludedEnd <= top) {
            listOf(this)
        } else {
            buildList {
                if (excludedStart > top) {
                    add(copy(bottom = excludedStart))
                }
                if (excludedEnd < bottom) {
                    add(copy(top = excludedEnd))
                }
            }
        }
    }
}
