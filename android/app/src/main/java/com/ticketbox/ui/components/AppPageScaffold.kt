package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.foundation.layout.RowScope
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppSpacing

enum class PageDensity {
    Compact,
    Comfortable,
}

enum class AppPageRole {
    Pending,
    Ledger,
    Stats,
    Settings,
    Edit,
    Auth,
}

typealias PageRole = AppPageRole

val PageRole.density: PageDensity
    get() = when (this) {
        PageRole.Ledger,
        PageRole.Edit -> PageDensity.Compact

        PageRole.Pending,
        PageRole.Stats,
        PageRole.Settings,
        PageRole.Auth -> PageDensity.Comfortable
    }

object AppPageDefaults {
    val HorizontalPadding: Dp = AppSpacing.screenHorizontal
    // Estimated floating bottom bar height including the surface and vertical margins.
    // Keep named so it can be replaced by measured layout height later.
    val BottomBarHeight: Dp = 96.dp
    val BottomContentExtraPadding: Dp = 24.dp
    val CardGap: Dp = AppSpacing.cardGap

    fun topContentPadding(density: PageDensity): Dp = when (density) {
        PageDensity.Compact -> 16.dp
        PageDensity.Comfortable -> 24.dp
    }

    fun headerToContentGap(density: PageDensity): Dp = when (density) {
        PageDensity.Compact -> 16.dp
        PageDensity.Comfortable -> 22.dp
    }

    fun sectionGap(density: PageDensity): Dp = when (density) {
        PageDensity.Compact -> 18.dp
        PageDensity.Comfortable -> 24.dp
    }
}

@Immutable
data class AppPageLayoutValues(
    val horizontalPadding: Dp,
    val statusPadding: Dp,
    val contentTopPadding: Dp,
    val bottomViewportPadding: Dp,
    val bottomContentExtraPadding: Dp,
    val topPadding: Dp,
    val bottomPadding: Dp,
    val headerToContentGap: Dp,
    val contentGap: Dp,
) {
    fun contentPadding(): PaddingValues = PaddingValues(
        start = horizontalPadding,
        top = topPadding,
        end = horizontalPadding,
        bottom = bottomPadding,
    )

    fun scrollContentPadding(): PaddingValues = PaddingValues(
        start = horizontalPadding,
        top = contentTopPadding,
        end = horizontalPadding,
        bottom = bottomContentExtraPadding,
    )
}

object BottomBarAwarePadding {
    @Composable
    fun viewport(hasBottomBar: Boolean): Dp {
        val density = LocalDensity.current
        val navigationBottom = with(density) { WindowInsets.navigationBars.getBottom(this).toDp() }
        return if (hasBottomBar) {
            AppPageDefaults.BottomBarHeight + navigationBottom
        } else {
            navigationBottom
        }
    }

    @Composable
    fun bottom(hasBottomBar: Boolean): Dp = viewport(hasBottomBar) + AppPageDefaults.BottomContentExtraPadding
}

@Composable
fun rememberAppPageLayout(
    role: PageRole,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = true,
): AppPageLayoutValues {
    val density = LocalDensity.current
    val statusTop = with(density) { WindowInsets.statusBars.getTop(this).toDp() }
    val safeTop = if (includeStatusBarPadding) {
        statusTop
    } else {
        0.dp
    }
    val bottomViewportPadding = BottomBarAwarePadding.viewport(hasBottomBar = hasBottomBar)
    val bottomPadding = bottomViewportPadding + AppPageDefaults.BottomContentExtraPadding
    val pageDensity = role.density
    val contentTopPadding = AppPageDefaults.topContentPadding(pageDensity)

    return AppPageLayoutValues(
        horizontalPadding = horizontalPadding,
        statusPadding = safeTop,
        contentTopPadding = contentTopPadding,
        bottomViewportPadding = bottomViewportPadding,
        bottomContentExtraPadding = AppPageDefaults.BottomContentExtraPadding,
        topPadding = safeTop + contentTopPadding,
        bottomPadding = bottomPadding,
        headerToContentGap = AppPageDefaults.headerToContentGap(pageDensity),
        contentGap = AppPageDefaults.sectionGap(pageDensity),
    )
}

@Composable
fun AppPageScaffold(
    role: PageRole,
    modifier: Modifier = Modifier,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = true,
    content: @Composable (AppPageLayoutValues) -> Unit,
) {
    val layout = rememberAppPageLayout(
        role = role,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
    )

    androidx.compose.foundation.layout.Box(modifier = modifier.fillMaxSize()) {
        content(layout)
    }
}

@Composable
fun AppPageScrollableColumn(
    role: PageRole,
    modifier: Modifier = Modifier,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = true,
    contentTopReduction: Dp = 0.dp,
    verticalArrangement: Arrangement.Vertical? = null,
    content: @Composable ColumnScope.(AppPageLayoutValues) -> Unit,
) {
    AppPageScaffold(
        role = role,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
        modifier = modifier.fillMaxSize(),
    ) { layout ->
        val adjustedContentTopPadding = (layout.contentTopPadding - contentTopReduction).coerceAtLeast(0.dp)

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(
                    top = layout.statusPadding,
                    bottom = layout.bottomViewportPadding,
                )
                .verticalScroll(rememberScrollState())
                .padding(horizontal = layout.horizontalPadding)
                .padding(
                    top = adjustedContentTopPadding,
                    bottom = layout.bottomContentExtraPadding,
                ),
            verticalArrangement = verticalArrangement ?: Arrangement.spacedBy(layout.contentGap),
        ) {
            content(layout)
        }
    }
}

@Composable
fun AppPageHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
    eyebrow: String = "小票夹",
    action: (@Composable RowScope.() -> Unit)? = null,
) {
    ScreenHeader(
        title = title,
        subtitle = subtitle,
        modifier = modifier,
        eyebrow = eyebrow,
        action = action,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppScrollableContent(
    role: PageRole,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    listState: LazyListState = rememberLazyListState(),
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = true,
    verticalArrangement: Arrangement.Vertical? = null,
    content: LazyListScope.() -> Unit,
) {
    AppPageScaffold(
        role = role,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
        modifier = modifier.fillMaxSize(),
    ) { layout ->
        PullToRefreshBox(
            isRefreshing = isRefreshing,
            onRefresh = onRefresh,
            modifier = Modifier.fillMaxSize(),
            indicator = {},
        ) {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(
                        top = layout.statusPadding,
                        bottom = layout.bottomViewportPadding,
                    ),
                state = listState,
                contentPadding = layout.scrollContentPadding(),
                verticalArrangement = verticalArrangement ?: Arrangement.spacedBy(layout.contentGap),
                content = content,
            )
        }
    }
}

@Composable
fun AppPageLazyColumn(
    role: PageRole,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    listState: LazyListState = rememberLazyListState(),
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = true,
    verticalArrangement: Arrangement.Vertical? = null,
    content: LazyListScope.() -> Unit,
) {
    AppScrollableContent(
        role = role,
        isRefreshing = isRefreshing,
        onRefresh = onRefresh,
        modifier = modifier,
        listState = listState,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
        verticalArrangement = verticalArrangement,
        content = content,
    )
}
