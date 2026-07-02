package com.ticketbox.ui.components

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.design.AppSpacing

data class AppSecondaryPageChrome(
    val role: AppPageRole,
    val title: String,
    val subtitle: String?,
    val backText: String,
    val onBack: (() -> Unit)?,
    val hasBottomBar: Boolean = false,
    val verticalArrangement: Arrangement.Vertical? = null,
)

data class AppSecondaryRefreshState(
    val isRefreshing: Boolean,
    val onRefresh: () -> Unit,
)

class AppSecondaryPageSlots(
    val status: (@Composable () -> Unit)? = null,
    val actions: (@Composable () -> Unit)? = null,
)

@Composable
fun AppSecondaryPageHeader(
    title: String,
    subtitle: String?,
    backText: String,
    onBack: (() -> Unit)?,
    actions: @Composable (() -> Unit)? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        onBack?.let {
            AppBackButton(text = backText, onClick = it)
        }
        if (actions == null) {
            AppPageHeader(title = title, subtitle = subtitle)
        } else {
            AppPageHeader(title = title, subtitle = subtitle) {
                actions()
            }
        }
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
        verticalArrangement = chrome.verticalArrangement,
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
