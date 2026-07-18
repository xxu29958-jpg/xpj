package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.StatsProductLoadingState
import com.ticketbox.viewmodel.DataQualityLoadState
import com.ticketbox.viewmodel.MonthlyStatsUiState

internal enum class DataQualityBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun dataQualityBodyState(state: MonthlyStatsUiState): DataQualityBodyState = when {
    state.dataQuality?.hasDataQualityAttention() == true -> DataQualityBodyState.Content
    state.dataQuality != null -> DataQualityBodyState.Empty
    state.dataQualityLoadState == DataQualityLoadState.Failed -> DataQualityBodyState.LoadFailed
    else -> DataQualityBodyState.Loading
}

@Composable
internal fun DataQualityScreen(
    state: MonthlyStatsUiState,
    onRefresh: () -> Unit,
    onRemediate: (DataQualityRemediation) -> Unit,
    onBack: () -> Unit,
) {
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.stats_data_quality_page_title),
            subtitle = stringResource(R.string.stats_data_quality_page_subtitle),
            backText = stringResource(R.string.stats_data_quality_back_to_insights),
            onBack = onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = state.dataQualityLoadState == DataQualityLoadState.Loading &&
                state.dataQuality != null,
            onRefresh = onRefresh,
        ),
    ) {
        dataQualityPageItems(
            state = state,
            onRefresh = onRefresh,
            onRemediate = onRemediate,
        )
    }
}

private fun LazyListScope.dataQualityPageItems(
    state: MonthlyStatsUiState,
    onRefresh: () -> Unit,
    onRemediate: (DataQualityRemediation) -> Unit,
) {
    val bodyState = dataQualityBodyState(state)
    if (state.dataQualityError != null && bodyState != DataQualityBodyState.LoadFailed) {
        item {
            AppStatusBanner(
                message = state.dataQualityError,
                tone = MessageTone.Danger,
            )
        }
    }
    when (bodyState) {
        DataQualityBodyState.Loading -> item { StatsProductLoadingState() }
        DataQualityBodyState.LoadFailed -> item {
            AppErrorState(
                title = stringResource(R.string.stats_data_quality_error_title),
                body = state.dataQualityError?.asString().orEmpty().ifBlank {
                    stringResource(R.string.stats_data_quality_load_failed)
                },
                onRetry = onRefresh,
            )
        }
        DataQualityBodyState.Empty -> item {
            EmptyStatsCard(
                title = stringResource(R.string.stats_data_quality_empty_title),
                body = stringResource(R.string.stats_data_quality_empty_body),
            )
        }
        DataQualityBodyState.Content -> state.dataQuality?.let { summary ->
            item {
                StatsInsightSurface {
                    PendingOverviewCard(
                        summary = summary,
                        onRemediate = onRemediate,
                    )
                }
            }
        }
    }
}
