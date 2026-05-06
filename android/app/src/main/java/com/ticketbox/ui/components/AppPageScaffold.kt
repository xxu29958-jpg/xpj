package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppSpacing

enum class AppPageRole {
    Pending,
    Ledger,
    Stats,
    Settings,
    Edit,
    Auth,
}

object AppPageDefaults {
    val HorizontalPadding: Dp = AppSpacing.screenHorizontal
    val MaxStatusBarPadding: Dp = 24.dp
    val BottomNavAvoidance: Dp = AppSpacing.bottomContentPadding

    fun topContentPadding(role: AppPageRole): Dp = when (role) {
        AppPageRole.Pending,
        AppPageRole.Stats,
        AppPageRole.Settings,
        AppPageRole.Auth -> 24.dp

        AppPageRole.Ledger -> 20.dp
        AppPageRole.Edit -> 18.dp
    }

    fun headerToContentGap(role: AppPageRole): Dp = when (role) {
        AppPageRole.Pending,
        AppPageRole.Stats -> 24.dp

        AppPageRole.Settings -> 22.dp
        AppPageRole.Ledger -> 18.dp
        AppPageRole.Edit,
        AppPageRole.Auth -> 16.dp
    }

    fun contentGap(role: AppPageRole): Dp = when (role) {
        AppPageRole.Pending,
        AppPageRole.Stats,
        AppPageRole.Settings -> AppSpacing.cardGap

        AppPageRole.Ledger -> 14.dp
        AppPageRole.Edit,
        AppPageRole.Auth -> 14.dp
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

@Composable
fun rememberAppPageLayout(
    role: AppPageRole,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = false,
): AppPageLayoutValues {
    val density = LocalDensity.current
    val statusTop = with(density) { WindowInsets.statusBars.getTop(this).toDp() }
    val navigationBottom = with(density) { WindowInsets.navigationBars.getBottom(this).toDp() }
    val safeTop = if (includeStatusBarPadding) {
        if (statusTop > AppPageDefaults.MaxStatusBarPadding) {
            AppPageDefaults.MaxStatusBarPadding
        } else {
            statusTop
        }
    } else {
        0.dp
    }
    val bottomPadding = if (hasBottomBar) {
        AppPageDefaults.BottomNavAvoidance
    } else {
        navigationBottom + 32.dp
    }

    return AppPageLayoutValues(
        horizontalPadding = horizontalPadding,
        topPadding = safeTop + AppPageDefaults.topContentPadding(role),
        bottomPadding = bottomPadding,
        headerToContentGap = AppPageDefaults.headerToContentGap(role),
        contentGap = AppPageDefaults.contentGap(role),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppPageLazyColumn(
    role: AppPageRole,
    isRefreshing: Boolean,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    hasBottomBar: Boolean = true,
    horizontalPadding: Dp = AppPageDefaults.HorizontalPadding,
    includeStatusBarPadding: Boolean = false,
    verticalArrangement: Arrangement.Vertical? = null,
    content: LazyListScope.() -> Unit,
) {
    val layout = rememberAppPageLayout(
        role = role,
        hasBottomBar = hasBottomBar,
        horizontalPadding = horizontalPadding,
        includeStatusBarPadding = includeStatusBarPadding,
    )

    PullToRefreshBox(
        isRefreshing = isRefreshing,
        onRefresh = onRefresh,
        modifier = modifier.fillMaxSize(),
        indicator = {},
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = layout.contentPadding(),
            verticalArrangement = verticalArrangement ?: Arrangement.spacedBy(layout.contentGap),
            content = content,
        )
    }
}
