package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ime
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
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing

enum class PageDensity {
    Compact,
    Comfortable,
}

enum class AppPageRole {
    Today,
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

        PageRole.Today,
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
    val BottomContentExtraPadding: Dp =
        AppSpacing.bottomContentPadding + AppSpacing.sectionGap + AppSpacing.cardGap
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

internal val LocalAppImeVisible = compositionLocalOf { false }

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

/**
 * 可滚动的页面列。可选 [bottomBar] 槽：传入时在 [Box] 底部居中浮一条操作栏。
 * 滚动**视口止于栏上沿**：按**实测**栏高（栏可能两行加提示，高度不固定，
 * 静态估算 [AppPageDefaults.BottomBarHeight] 会算少）收缩视口，而不是把栏高
 * 折成滚动内容的底 padding。后者会让视口延伸到栏背后——"最小滚动"类的
 * bring-into-view（无障碍聚焦、测试 `performScrollTo`）把目标停在视口底缘
 * 即栏底下，看似可见、点击却被栏吃掉。传 [bottomBar] 时调用方应让
 * `hasBottomBar = false`（不要再叠静态估算）。
 *
 * 栏自己负责导航栏 inset（实测高度已含），所以视口收缩量就是栏高本身；
 * 软键盘 inset 由外层 [AppPageScaffold] 的 `imePadding()` 统一处理，槽内
 * 不要再叠一层。`bottomBar` 默认 `null`——既有调用方零影响。
 */
@Composable
fun AppPageScrollableColumn(
    role: PageRole,
    modifier: Modifier = Modifier,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = true,
    verticalArrangement: Arrangement.Vertical? = null,
    bottomBar: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.(AppPageLayoutValues) -> Unit,
) {
    val density = LocalDensity.current
    val keyboardVisible = WindowInsets.ime.getBottom(density) > 0
    var bottomBarHeight by remember { mutableStateOf(0.dp) }

    AppPageScaffold(
        role = role,
        modifier = modifier,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
    ) { layout ->
        // align(BottomCenter) needs a BoxScope — the scaffold's content lambda has
        // no receiver, so the column + floating bar pair gets its own Box root.
        Box(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(
                        top = layout.statusPadding,
                        // 栏自带导航栏 inset，实测高度已覆盖 bottomViewportPadding
                        // 的导航栏份额，二者取一不叠加。
                        bottom = if (bottomBar != null) bottomBarHeight else layout.bottomViewportPadding,
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
            if (bottomBar != null) {
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .onSizeChanged { bottomBarHeight = with(density) { it.height.toDp() } },
                ) {
                    CompositionLocalProvider(LocalAppImeVisible provides keyboardVisible) {
                        bottomBar()
                    }
                }
            }
        }
    }
}

@Composable
fun AppPageHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
    eyebrow: String = stringResource(R.string.components_page_header_eyebrow),
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
