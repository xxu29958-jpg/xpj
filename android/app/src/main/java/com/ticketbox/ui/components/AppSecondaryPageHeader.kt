package com.ticketbox.ui.components

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.asTextStyle

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
    val headingPrefix: (@Composable () -> Unit)? = null,
)

internal fun AppSecondaryPageSlots.resolveBottomBar(
    explicitBottomBar: (@Composable () -> Unit)? = null,
): (@Composable () -> Unit)? = explicitBottomBar ?: bottomBar

private fun AppSecondaryPageChrome.toScrollablePageChrome(): AppScrollablePageChrome =
    AppScrollablePageChrome(
        page = AppPageChrome(
            role = role,
            hasBottomBar = hasBottomBar,
        ),
        contentWidth = contentWidth,
        verticalArrangement = verticalArrangement,
    )

@Composable
fun AppSecondaryPageHeader(
    title: String,
    subtitle: String?,
    backText: String,
    onBack: (() -> Unit)?,
    slots: AppSecondaryPageSlots = AppSecondaryPageSlots(),
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
    ) {
        onBack?.let { AppBackButton(text = backText, onClick = it) }
        slots.headingPrefix?.invoke()
        AppSecondaryTitleText(title = title, subtitle = subtitle, modifier = Modifier.fillMaxWidth())
        slots.actions?.invoke()
    }
}

@Composable
private fun AppSecondaryTitleText(
    title: String,
    subtitle: String?,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = title,
            style = AppTextHierarchy.hero.asTextStyle(),
            modifier = Modifier.semantics { heading() },
        )
        subtitle?.takeIf { it.isNotBlank() }?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
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
        chrome = AppScrollableContentChrome(
            role = chrome.role,
            layout = AppScrollableContentLayout(
                hasBottomBar = chrome.hasBottomBar,
                contentWidth = chrome.contentWidth,
                verticalArrangement = chrome.verticalArrangement,
            ),
            bottomBar = slots.resolveBottomBar(),
        ),
        refresh = AppScrollableRefreshState(
            isRefreshing = refresh.isRefreshing,
            onRefresh = refresh.onRefresh,
        ),
        modifier = modifier,
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
        chrome = chrome.toScrollablePageChrome(),
        modifier = modifier,
        bottomBar = slots.resolveBottomBar(bottomBar),
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
        slots = slots,
    )
}

@Composable
private fun SecondaryBackHandler(onBack: (() -> Unit)?) {
    BackHandler(enabled = onBack != null) {
        onBack?.invoke()
    }
}
