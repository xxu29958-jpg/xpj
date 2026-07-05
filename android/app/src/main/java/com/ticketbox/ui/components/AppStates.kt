package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalStateTokens
import com.valentinilk.shimmer.shimmer

@Immutable
data class AppListStateSpec(
    val isEmpty: Boolean,
    val loading: Boolean,
    val emptyText: String,
    val skeletonRows: Int = 3,
    val emptyTitle: String? = null,
    val emptyBody: String? = null,
)

@Immutable
data class AppContentStateCopy(
    val loadingTitle: String,
    val loadingBody: String? = null,
    val emptyText: String,
    val emptyTitle: String? = null,
    val emptyBody: String? = null,
)

enum class AppContentStatePresentation {
    Card,
    Inline,
}

@Immutable
data class AppContentStateSpec(
    val loading: Boolean,
    val hasData: Boolean,
    val copy: AppContentStateCopy,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val presentation: AppContentStatePresentation = AppContentStatePresentation.Card,
    val showLoadingWithData: Boolean = false,
)

/**
 * 统一加载占位组件。
 *
 * - 内部使用 [AppEmptyStateCard]，与空状态共享卡片底版。
 * - 仅做展示职责：不发起任何业务调用，由调用方决定何时显示。
 *
 * v0.10：进度条改为 [SkeletonScaffold] 包裹的骸屏行，按 [com.ticketbox.ui.design.LocalSkeletonTokens]
 * 渲染主题色板（midnight 用暖金 alpha，paper/mono 用墨灰）。调用方签名不变；若调用方未来升级为
 * "接管 isLoading 切换"，可以直接换用 [SkeletonScaffold]。
 */
@Composable
fun AppLoadingState(
    title: String,
    body: String? = null,
    modifier: Modifier = Modifier,
) {
    AppEmptyStateCard(modifier = modifier) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            body?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            SkeletonScaffold(
                isLoading = true,
                skeleton = {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        SkeletonBlock(modifier = Modifier.fillMaxWidth(fraction = 0.78f).height(10.dp))
                        SkeletonBlock(modifier = Modifier.fillMaxWidth(fraction = 0.55f).height(10.dp))
                    }
                },
                content = {},
            )
        }
    }
}

@Composable
fun AppListStateContent(
    state: AppListStateSpec,
    modifier: Modifier = Modifier,
    rows: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        when {
            state.isEmpty && state.loading -> Column(modifier = Modifier.shimmer()) {
                repeat(state.skeletonRows.coerceAtLeast(1)) {
                    ListItemSkeleton(horizontalPadding = AppSpacing.none)
                }
            }
            state.isEmpty -> AppContentStateSlot(
                state = AppContentStateSpec(
                    loading = false,
                    hasData = false,
                    copy = AppContentStateCopy(
                        loadingTitle = "",
                        emptyText = state.emptyText,
                        emptyTitle = state.emptyTitle,
                        emptyBody = state.emptyBody,
                    ),
                    presentation = AppContentStatePresentation.Inline,
                ),
            )
            else -> rows()
        }
    }
}

@Composable
fun AppContentStateSlot(
    state: AppContentStateSpec,
    modifier: Modifier = Modifier,
) {
    val visibleMessage = state.message?.takeIf { it.asString().isNotBlank() }
    when {
        state.loading && (!state.hasData || state.showLoadingWithData) -> AppContentLoadingState(
            copy = state.copy,
            modifier = modifier,
            presentation = state.presentation,
        )
        visibleMessage != null -> AppStatusBanner(
            message = visibleMessage,
            tone = state.messageTone,
            modifier = modifier,
        )
        !state.hasData -> AppContentEmptyState(
            copy = state.copy,
            modifier = modifier,
            presentation = state.presentation,
        )
    }
}

@Composable
private fun AppContentLoadingState(
    copy: AppContentStateCopy,
    modifier: Modifier,
    presentation: AppContentStatePresentation,
) {
    when (presentation) {
        AppContentStatePresentation.Card -> AppLoadingState(
            title = copy.loadingTitle,
            body = copy.loadingBody,
            modifier = modifier,
        )
        AppContentStatePresentation.Inline -> AppInlineStateBlock(
            title = copy.loadingTitle,
            body = copy.loadingBody,
            modifier = modifier,
        )
    }
}

@Composable
private fun AppContentEmptyState(
    copy: AppContentStateCopy,
    modifier: Modifier,
    presentation: AppContentStatePresentation,
) {
    val title = copy.emptyTitle
    val body = copy.emptyBody ?: copy.emptyText
    when (presentation) {
        AppContentStatePresentation.Card -> AppEmptyStateCard(modifier = modifier) {
            AppStateTextBlock(
                title = title,
                body = body,
                titleStyle = MaterialTheme.typography.titleSmall,
                bodyStyle = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            )
        }
        AppContentStatePresentation.Inline -> {
            if (title != null) {
                AppInlineStateBlock(
                    title = title,
                    body = body,
                    modifier = modifier,
                )
            } else {
                Text(
                    modifier = modifier,
                    text = copy.emptyText,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

@Composable
private fun AppInlineStateBlock(
    title: String,
    body: String?,
    modifier: Modifier,
) {
    AppStateTextBlock(
        title = title,
        body = body,
        titleStyle = MaterialTheme.typography.titleSmall,
        bodyStyle = MaterialTheme.typography.bodySmall,
        modifier = modifier.padding(vertical = AppSpacing.miniGap),
    )
}

@Composable
private fun AppStateTextBlock(
    title: String?,
    body: String?,
    titleStyle: TextStyle,
    bodyStyle: TextStyle,
    modifier: Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        title?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                style = titleStyle,
                fontWeight = AppTextHierarchy.heading.weight,
            )
        }
        body?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = bodyStyle,
            )
        }
    }
}

/**
 * 统一错误态组件（审计 8.4）。
 *
 * 一笔加载**失败**（而不是没有数据 / 正在加载）时显示：说明文案 + 「重试」。在此组件出现前，
 * 失败常被加载态或空态冒充——Budget 失败后常驻「正在读取预算。」（永远不会变）、Stats 失败
 * 落到看着像没数据的空态卡。语义对标编辑页：有原因说明 + 可重试。
 *
 * - 卡片底版复用 [AppEmptyStateCard]，与空 / 加载态共享视觉语言（不自创视觉）。
 * - 强调色取 [com.ticketbox.ui.design.StateTokens.danger]（与 [AppStatusBanner] 的 danger
 *   分支同源、三主题 paper/mono/midnight 视差对齐），用 token 不写死色值，三主题自然可读。
 * - 仅做展示与回调；何时显示、[onRetry] 触发什么由调用方决定（一般是 VM 的 refresh）。
 */
@Composable
fun AppErrorState(
    title: String,
    body: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val danger = LocalStateTokens.current.danger
    AppEmptyStateCard(modifier = modifier) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(AppRadius.medium))
                    .background(danger.bg)
                    .border(1.dp, danger.border, RoundedCornerShape(AppRadius.medium))
                    .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactGap),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                Text(
                    text = title,
                    color = danger.fg,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = body,
                    color = danger.fg,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            AppSecondaryButton(
                text = stringResource(R.string.common_retry),
                modifier = Modifier.fillMaxWidth(),
                onClick = onRetry,
            )
        }
    }
}
