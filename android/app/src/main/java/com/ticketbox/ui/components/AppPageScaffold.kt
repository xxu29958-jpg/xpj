package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
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
    val MaxStatusBarPadding: Dp = 24.dp
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
}

object BottomBarAwarePadding {
    @Composable
    fun bottom(hasBottomBar: Boolean): Dp {
        val density = LocalDensity.current
        val navigationBottom = with(density) { WindowInsets.navigationBars.getBottom(this).toDp() }
        return if (hasBottomBar) {
            // Current floating bottom bar measured visually near this height; keep named until measured layout is available.
            AppPageDefaults.BottomBarHeight + navigationBottom + AppPageDefaults.BottomContentExtraPadding
        } else {
            navigationBottom + AppPageDefaults.BottomContentExtraPadding
        }
    }
}

@Composable
fun rememberAppPageLayout(
    role: PageRole,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = false,
): AppPageLayoutValues {
    val density = LocalDensity.current
    val statusTop = with(density) { WindowInsets.statusBars.getTop(this).toDp() }
    val safeTop = if (includeStatusBarPadding) {
        if (statusTop > AppPageDefaults.MaxStatusBarPadding) {
            AppPageDefaults.MaxStatusBarPadding
        } else {
            statusTop
        }
    } else {
        0.dp
    }
    val bottomPadding = BottomBarAwarePadding.bottom(hasBottomBar = hasBottomBar)
    val pageDensity = role.density

    return AppPageLayoutValues(
        horizontalPadding = horizontalPadding,
        topPadding = safeTop + AppPageDefaults.topContentPadding(pageDensity),
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
    includeStatusBarPadding: Boolean = false,
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
    includeStatusBarPadding: Boolean = false,
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
                modifier = Modifier.fillMaxSize(),
                state = listState,
                contentPadding = layout.contentPadding(),
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
    includeStatusBarPadding: Boolean = false,
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
