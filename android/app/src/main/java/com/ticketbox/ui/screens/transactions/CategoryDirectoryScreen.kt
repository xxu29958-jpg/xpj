package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryPreference
import com.ticketbox.domain.model.CategoryReference
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.screens.settings.SettingsDetailRow
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.CategoryDirectoryUiState
import com.ticketbox.viewmodel.CategoryDirectoryViewModel

@Composable
fun CategoryDirectoryScreen(
    viewModel: CategoryDirectoryViewModel,
    onBack: () -> Unit,
    onCategoriesChanged: () -> Unit = {},
    onOpenReference: (CategoryReference) -> Unit = {},
    creation: @Composable (Boolean) -> Unit = {},
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(state.changedRevision) {
        if (state.changedRevision > 0) onCategoriesChanged()
    }

    CategoryInspectionDialog(state, viewModel, onOpenReference)

    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.category_directory_title),
            subtitle = if (state.customCategories.isEmpty() && (state.loading || state.loadFailed)) {
                stringResource(if (state.loading) R.string.category_directory_loading
                    else R.string.category_directory_load_failed)
            } else stringResource(
                R.string.category_directory_subtitle,
                DEFAULT_EXPENSE_CATEGORIES.size,
                state.customCategories.size,
            ),
            backText = stringResource(R.string.transactions_library_back_to_library),
            onBack = onBack,
        ),
        slots = AppSecondaryPageSlots(
            status = {
                AppStatusBanner(
                    message = state.message,
                    tone = state.messageTone,
                )
            },
        ),
    ) {
        if (!state.canModify) {
            Text(
                text = stringResource(R.string.category_directory_readonly),
                color = MaterialTheme.colorScheme.tertiary,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        CustomCategoriesCard(
            state = state,
            onRetry = viewModel::refresh,
            onInspect = viewModel::inspect,
        )
        DefaultCategoriesCard()
        Text(stringResource(R.string.category_directory_creation_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        creation(!state.loading && state.busyCategoryId == null)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DefaultCategoriesCard() {
    SettingsDetailRow(
        title = stringResource(R.string.category_directory_default_title),
        subtitle = stringResource(R.string.category_directory_default_body),
        icon = R.drawable.ic_lucide_shapes,
    ) {
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            DEFAULT_EXPENSE_CATEGORIES.forEach { name ->
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(AppRadius.pill))
                        .background(MaterialTheme.colorScheme.secondaryContainer)
                        .padding(
                            horizontal = AppSpacing.compactGap,
                            vertical = AppSpacing.smallGap,
                        ),
                ) {
                    Text(
                        text = name,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
        }
    }
}

@Composable
private fun CustomCategoriesCard(
    state: CategoryDirectoryUiState,
    onRetry: () -> Unit,
    onInspect: (CategoryPreference) -> Unit,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.category_directory_custom_title),
            style = MaterialTheme.typography.titleMedium,
        )
        if (state.loadFailed && state.customCategories.isNotEmpty()) {
            Text(stringResource(R.string.category_directory_stale),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = onRetry) { Text(stringResource(R.string.category_directory_retry)) }
        }
        when {
            state.loading && state.customCategories.isEmpty() -> Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator()
            }
            state.loadFailed && state.customCategories.isEmpty() -> CategoryLoadFailed(onRetry = onRetry)
            state.customCategories.isEmpty() -> Text(
                text = stringResource(R.string.category_directory_custom_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            else -> state.customCategories.forEachIndexed { index, category ->
                CategoryPreferenceRow(
                    category = category,
                    busy = state.busyCategoryId != null,
                    showDivider = index < state.customCategories.lastIndex,
                    onInspect = { onInspect(category) },
                )
            }
        }
    }
}

@Composable
private fun CategoryLoadFailed(
    onRetry: () -> Unit,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.category_directory_load_failed),
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppPrimaryButton(text = stringResource(R.string.category_directory_retry), onClick = onRetry)
    }
}

@Composable
private fun CategoryPreferenceRow(
    category: CategoryPreference,
    busy: Boolean,
    showDivider: Boolean,
    onInspect: () -> Unit,
) {
    AppListRow(showDivider = showDivider) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_shapes),
                background = LocalThemeVisuals.current.surfaceApricot)
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = category.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.category_directory_usage_count, category.usageCount),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            IconButton(
                enabled = !busy,
                onClick = onInspect,
            ) {
                Icon(
                    imageVector = ImageVector.vectorResource(R.drawable.ic_lucide_chevron_right),
                    contentDescription = stringResource(
                        R.string.category_directory_delete_description,
                        category.name,
                    ),
                )
            }
        }
    }
}
