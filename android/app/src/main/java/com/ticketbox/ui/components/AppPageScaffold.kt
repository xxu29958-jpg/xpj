package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.PullToRefreshDefaults
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
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

    // 浮动底栏（含上下外边距）的估算高度。后续若改为实测高度，
    // 仅需在这里替换。
    val BottomBarHeight: Dp = 96.dp
    val BottomContentExtraPadding: Dp = AppSpacing.bottomContentPadding
    val CardGap: Dp = AppSpacing.cardGap

    fun topContentPadding(density: PageDensity): Dp = when (density) {
        PageDensity.Compact -> 14.dp
        PageDensity.Comfortable -> 18.dp
    }

    /**
     * 页头与正文之间的间隙。
     *
     * 当前由各页面自行控制 header 下方间距，骨架本身只用 [sectionGap] 串联
     * 所有正文块；这里保留 token 是为了让密度规则保持自洽，并供 UI 单元测试断言。
     */
    fun headerToContentGap(density: PageDensity): Dp = when (density) {
        PageDensity.Compact -> 12.dp
        PageDensity.Comfortable -> AppSpacing.cardGap
    }

    fun sectionGap(density: PageDensity): Dp = when (density) {
        PageDensity.Compact -> 12.dp
        PageDensity.Comfortable -> AppSpacing.cardGap
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
    val safeTop = if (includeStatusBarPadding) statusTop else 0.dp
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
        contentGap = AppPageDefaults.sectionGap(pageDensity),
    )
}

/**
 * 页面骨架。统一负责：
 * - 占满整屏 (`fillMaxSize`)
 * - 软键盘 inset (`imePadding`)，由所有子骨架共享
 * - 提供 [AppPageLayoutValues]，子骨架按需要应用顶/底 inset 与水平内边距
 *
 * 调用方不需要也不应该再次 `fillMaxSize()` / `imePadding()`。
 */
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

    Box(
        modifier = modifier
            .fillMaxSize()
            .imePadding(),
    ) {
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
    verticalArrangement: Arrangement.Vertical? = null,
    content: @Composable ColumnScope.(AppPageLayoutValues) -> Unit,
) {
    AppPageScaffold(
        role = role,
        modifier = modifier,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
    ) { layout ->
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
                    top = layout.contentTopPadding,
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
        modifier = modifier,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
    ) { layout ->
        val refreshState = rememberPullToRefreshState()
        PullToRefreshBox(
            isRefreshing = isRefreshing,
            onRefresh = onRefresh,
            modifier = Modifier.fillMaxSize(),
            state = refreshState,
            indicator = {
                // Material3 默认 indicator，避免下拉时只见手指不见反馈。
                // 位置在 status bar 下方一格，与列表 contentPadding 一致。
                PullToRefreshDefaults.Indicator(
                    state = refreshState,
                    isRefreshing = isRefreshing,
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = layout.statusPadding + 4.dp),
                )
            },
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
