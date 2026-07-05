package com.ticketbox.ui.components

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

data class AppSecondaryPageChrome(
    val role: AppPageRole,
    val title: String,
    val subtitle: String?,
    val backText: String,
    val onBack: (() -> Unit)?,
    val hasBottomBar: Boolean = false,
    val contentWidth: AppAdaptiveContentWidth = AppAdaptiveContentWidth.Secondary,
    val verticalArrangement: Arrangement.Vertical? = null,
)

data class AppSecondaryRefreshState(
    val isRefreshing: Boolean,
    val onRefresh: () -> Unit,
)

class AppSecondaryPageSlots(
    val status: (@Composable () -> Unit)? = null,
    val actions: (@Composable () -> Unit)? = null,
    val bottomBar: (@Composable () -> Unit)? = null,
)

@Composable
fun AppSecondaryPageHeader(
    title: String,
    subtitle: String?,
    backText: String,
    onBack: (() -> Unit)?,
    actions: @Composable (() -> Unit)? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        onBack?.let {
            AppBackButton(text = backText, onClick = it)
        }
        AppSecondaryTitleBlock(title = title, subtitle = subtitle, actions = actions)
    }
}

@Composable
private fun AppSecondaryTitleBlock(
    title: String,
    subtitle: String?,
    actions: @Composable (() -> Unit)?,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontSize = AppTextHierarchy.heading.size,
                    lineHeight = 24.sp,
                    letterSpacing = 0.sp,
                ),
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            subtitle?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.heavy),
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontSize = AppTextHierarchy.caption.size,
                        lineHeight = 18.sp,
                        letterSpacing = 0.sp,
                    ),
                    fontWeight = AppTextHierarchy.caption.weight,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        actions?.invoke()
    }
}

@Composable
fun AppSecondaryScrollableContent(
    chrome: AppSecondaryPageChrome,
    refresh: AppSecondaryRefreshState,
    modifier: Modifier = Modifier,
    slots: AppSecondaryPageSlots = AppSecondaryPageSlots(),
    content: LazyListScope.() -> Unit,
) {
    SecondaryBackHandler(chrome.onBack)

    AppScrollableContent(
        role = chrome.role,
        isRefreshing = refresh.isRefreshing,
        onRefresh = refresh.onRefresh,
        modifier = modifier,
        hasBottomBar = chrome.hasBottomBar,
        contentWidth = chrome.contentWidth,
        verticalArrangement = chrome.verticalArrangement,
        bottomBar = slots.bottomBar,
    ) {
        item { SecondaryHeader(chrome = chrome, slots = slots) }
        slots.status?.let { status -> item { status() } }
        content()
    }
}

@Composable
fun AppSecondaryScrollableColumn(
    chrome: AppSecondaryPageChrome,
    modifier: Modifier = Modifier,
    slots: AppSecondaryPageSlots = AppSecondaryPageSlots(),
    bottomBar: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.(AppPageLayoutValues) -> Unit,
) {
    SecondaryBackHandler(chrome.onBack)

    AppPageScrollableColumn(
        role = chrome.role,
        modifier = modifier,
        hasBottomBar = chrome.hasBottomBar,
        contentWidth = chrome.contentWidth,
        verticalArrangement = chrome.verticalArrangement,
        bottomBar = bottomBar,
    ) { layout ->
        SecondaryHeader(chrome = chrome, slots = slots)
        slots.status?.invoke()
        content(layout)
    }
}

@Composable
private fun SecondaryHeader(
    chrome: AppSecondaryPageChrome,
    slots: AppSecondaryPageSlots,
) {
    AppSecondaryPageHeader(
        title = chrome.title,
        subtitle = chrome.subtitle,
        backText = chrome.backText,
        onBack = chrome.onBack,
        actions = slots.actions,
    )
}

@Composable
private fun SecondaryBackHandler(onBack: (() -> Unit)?) {
    BackHandler(enabled = onBack != null) {
        onBack?.invoke()
    }
}
