package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.BoxWithConstraintsScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsIgnoringVisibility
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.PullToRefreshDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshState
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
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppAdaptiveContentWidth
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
        PageRole.Edit,
        PageRole.Settings -> PageDensity.Compact

        PageRole.Today,
        PageRole.Pending,
        PageRole.Stats,
        PageRole.Auth -> PageDensity.Comfortable
    }

object AppPageDefaults {
    val HorizontalPadding: Dp = AppSpacing.screenHorizontal

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

/**
 * True only while the outer Material scaffold has already inset content by a
 * measured compact-window navigation bar. Pages then must not guess or add a
 * second navigation-bar inset.
 */
internal val LocalPrimaryNavigationInsetHandled = compositionLocalOf { false }

/**
 * True while the product shell already owns the status-bar inset through its
 * global domain bar. Primary pages then start below that bar instead of adding
 * the system inset a second time. Secondary pages keep their own inset because
 * the shell bar is intentionally absent while drilling in.
 */
internal val LocalPrimaryStatusInsetHandled = compositionLocalOf { false }

@Immutable
data class AppPageChrome(
    val role: PageRole,
    val hasBottomBar: Boolean = true,
    val horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    val includeStatusBarPadding: Boolean = true,
)

data class AppScrollablePageChrome(
    val page: AppPageChrome,
    val contentWidth: AppAdaptiveContentWidth = AppAdaptiveContentWidth.FullWidth,
    val verticalArrangement: Arrangement.Vertical? = null,
)

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
    fun viewport(): Dp {
        if (LocalPrimaryNavigationInsetHandled.current) return 0.dp
        val density = LocalDensity.current
        return with(density) { WindowInsets.navigationBars.getBottom(this).toDp() }
    }

    @Composable
    fun bottom(): Dp = viewport() + AppPageDefaults.BottomContentExtraPadding
}

@Composable
@OptIn(ExperimentalLayoutApi::class)
fun rememberAppPageLayout(
    chrome: AppPageChrome,
): AppPageLayoutValues {
    val context = LocalContext.current
    val density = LocalDensity.current
    val view = LocalView.current
    val statusTop = with(density) {
        val resourceStatusTop = context.resources
            .getIdentifier("status_bar_height", "dimen", "android")
            .takeIf { it > 0 }
            ?.let { context.resources.getDimensionPixelSize(it).toDp() }
            ?: 0.dp
        val viewStatusTop = ViewCompat.getRootWindowInsets(view)
            ?.getInsetsIgnoringVisibility(WindowInsetsCompat.Type.statusBars())
            ?.top
            ?.toDp()
            ?: 0.dp
        val measuredStatusTop = maxOf(
            WindowInsets.statusBars.getTop(this).toDp(),
            WindowInsets.statusBarsIgnoringVisibility.getTop(this).toDp(),
            viewStatusTop,
            resourceStatusTop,
        )
        measuredStatusTop
    }
    val safeTop = resolveStatusPadding(
        includeStatusBarPadding = chrome.includeStatusBarPadding,
        shellInsetHandled = LocalPrimaryStatusInsetHandled.current,
        measuredStatusPadding = statusTop,
    )
    val bottomViewportPadding = BottomBarAwarePadding.viewport()
    val bottomPadding = bottomViewportPadding + AppPageDefaults.BottomContentExtraPadding
    val pageDensity = chrome.role.density
    val contentTopPadding = AppPageDefaults.topContentPadding(pageDensity)

    return AppPageLayoutValues(
        horizontalPadding = chrome.horizontalPadding,
        statusPadding = safeTop,
        contentTopPadding = contentTopPadding,
        bottomViewportPadding = bottomViewportPadding,
        bottomContentExtraPadding = AppPageDefaults.BottomContentExtraPadding,
        topPadding = safeTop + contentTopPadding,
        bottomPadding = bottomPadding,
        contentGap = AppPageDefaults.sectionGap(pageDensity),
    )
}

internal fun resolveStatusPadding(
    includeStatusBarPadding: Boolean,
    shellInsetHandled: Boolean,
    measuredStatusPadding: Dp,
): Dp = if (includeStatusBarPadding && !shellInsetHandled) measuredStatusPadding else 0.dp

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
    chrome: AppPageChrome,
    modifier: Modifier = Modifier,
    content: @Composable (AppPageLayoutValues) -> Unit,
) {
    val layout = rememberAppPageLayout(chrome = chrome)

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
 * 滚动**视口止于栏上沿**：按**实测**栏高（栏可能两行加提示，高度不固定）
 * 收缩视口，而不是把栏高
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
    chrome: AppScrollablePageChrome,
    modifier: Modifier = Modifier,
    bottomBar: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.(AppPageLayoutValues) -> Unit,
) {
    val density = LocalDensity.current
    val keyboardVisible = WindowInsets.ime.getBottom(density) > 0
    var bottomBarHeight by remember { mutableStateOf(0.dp) }

    AppPageScaffold(
        chrome = chrome.page,
        modifier = modifier,
    ) { layout ->
        // align(BottomCenter) needs a BoxScope — the scaffold's content lambda has
        // no receiver, so the column + floating bar pair gets its own Box root.
        CompositionLocalProvider(LocalAppImeVisible provides keyboardVisible) {
            BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
                val resolvedContentMaxWidth = resolvedContentMaxWidth(chrome.contentWidth)
                Box(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxHeight()
                        .appPageContentWidth(resolvedContentMaxWidth)
                        .padding(
                            top = layout.statusPadding,
                            // 栏自带导航栏 inset，实测高度已覆盖 bottomViewportPadding
                            // 的导航栏份额，二者取一不叠加。
                            bottom = if (bottomBar != null) bottomBarHeight else layout.bottomViewportPadding,
                        )
                        .clipToBounds(),
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(horizontal = layout.horizontalPadding)
                            .padding(
                                top = layout.contentTopPadding,
                                bottom = layout.bottomContentExtraPadding,
                            ),
                        verticalArrangement = chrome.verticalArrangement ?: Arrangement.spacedBy(layout.contentGap),
                    ) {
                        content(layout)
                    }
                }
                if (bottomBar != null) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            // 只约束最大宽度让栏与正文列对齐；横向 inset 由栏自己负责
                            // （AppFloatingActionBar 已 padding screenHorizontal），这里不再叠一层。
                            .appPageContentWidthOnly(resolvedContentMaxWidth)
                            .onSizeChanged { bottomBarHeight = with(density) { it.height.toDp() } },
                    ) {
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
    eyebrow: String = "",
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
    chrome: AppScrollableContentChrome,
    refresh: AppScrollableRefreshState,
    modifier: Modifier = Modifier,
    listState: LazyListState = rememberLazyListState(),
    content: LazyListScope.() -> Unit,
) {
    val density = LocalDensity.current
    val keyboardVisible = WindowInsets.ime.getBottom(density) > 0
    var bottomBarHeight by remember { mutableStateOf(0.dp) }

    AppPageScaffold(
        chrome = AppPageChrome(
            role = chrome.role,
            hasBottomBar = chrome.layout.hasBottomBar,
            horizontalPadding = chrome.layout.horizontalPadding,
            includeStatusBarPadding = chrome.layout.includeStatusBarPadding,
        ),
        modifier = modifier,
    ) { layout ->
        val refreshState = rememberPullToRefreshState()
        CompositionLocalProvider(LocalAppImeVisible provides keyboardVisible) {
            BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
                val resolvedContentMaxWidth = resolvedContentMaxWidth(chrome.layout.contentWidth)
                PullToRefreshBox(
                    isRefreshing = refresh.isRefreshing,
                    onRefresh = refresh.onRefresh,
                    modifier = Modifier.fillMaxSize(),
                    state = refreshState,
                    indicator = {
                        // Material3 默认 indicator，避免下拉时只见手指不见反馈。
                        // 位置在页面视口上沿下方一格：shell 已接管状态栏时 statusPadding 为 0，
                        // 未接管（二级页）时为实测状态栏高，均不再额外叠加。
                        AppPullToRefreshIndicator(refreshState, refresh.isRefreshing, layout.statusPadding)
                    },
                ) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .fillMaxHeight()
                            .appPageContentWidth(resolvedContentMaxWidth)
                            .padding(
                                top = layout.statusPadding,
                                bottom = if (chrome.bottomBar != null) bottomBarHeight else layout.bottomViewportPadding,
                            )
                            .clipToBounds(),
                    ) {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            state = listState,
                            contentPadding = layout.scrollContentPadding(),
                            verticalArrangement = chrome.layout.verticalArrangement ?: Arrangement.spacedBy(layout.contentGap),
                            content = content,
                        )
                    }
                }
                chrome.bottomBar?.let { bottomBar ->
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .onSizeChanged { bottomBarHeight = with(density) { it.height.toDp() } },
                    ) {
                        bottomBar()
                    }
                }
            }
        }
    }
}

class AppScrollableContentChrome(
    val role: PageRole,
    val layout: AppScrollableContentLayout = AppScrollableContentLayout(),
    val bottomBar: (@Composable () -> Unit)? = null,
)

data class AppScrollableContentLayout(
    val hasBottomBar: Boolean = true,
    val horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    val includeStatusBarPadding: Boolean = true,
    val contentWidth: AppAdaptiveContentWidth = AppAdaptiveContentWidth.FullWidth,
    val verticalArrangement: Arrangement.Vertical? = null,
)

data class AppScrollableRefreshState(
    val isRefreshing: Boolean,
    val onRefresh: () -> Unit,
)

private fun Modifier.appPageContentWidth(maxWidth: Dp?): Modifier =
    if (maxWidth == null) {
        fillMaxSize()
    } else {
        widthIn(max = maxWidth).fillMaxSize()
    }

// 宽度专用版：浮动底栏只需要横向对齐正文，[appPageContentWidth] 的
// fillMaxSize 会把栏拉成整屏高，不能用在那里。
private fun Modifier.appPageContentWidthOnly(maxWidth: Dp?): Modifier =
    if (maxWidth == null) {
        fillMaxWidth()
    } else {
        widthIn(max = maxWidth).fillMaxWidth()
    }

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun BoxScope.AppPullToRefreshIndicator(
    state: PullToRefreshState,
    isRefreshing: Boolean,
    topPadding: Dp,
) {
    PullToRefreshDefaults.Indicator(
        state = state,
        isRefreshing = isRefreshing,
        modifier = Modifier
            .align(Alignment.TopCenter)
            .padding(top = topPadding + AppSpacing.miniGap),
    )
}

private fun BoxWithConstraintsScope.resolvedContentMaxWidth(
    contentWidth: AppAdaptiveContentWidth,
): Dp? = AppAdaptiveBreakpoints.contentMaxWidthFor(
    policy = contentWidth,
    maxWidth = maxWidth,
)
