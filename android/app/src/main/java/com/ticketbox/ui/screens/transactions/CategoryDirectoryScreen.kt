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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryPreference
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.ui.components.AppContentCard
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
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var pendingDelete by remember { mutableStateOf<CategoryPreference?>(null) }

    LaunchedEffect(state.changedRevision) {
        if (state.changedRevision > 0) onCategoriesChanged()
    }

    pendingDelete?.let { category ->
        CategoryDeleteDialog(
            category = category,
            onDismiss = { pendingDelete = null },
            onConfirm = {
                pendingDelete = null
                viewModel.delete(category)
            },
        )
    }

    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.category_directory_title),
            subtitle = stringResource(
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
        DefaultCategoriesCard()
        CustomCategoriesCard(
            state = state,
            onRetry = viewModel::refresh,
            onDelete = { pendingDelete = it },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DefaultCategoriesCard() {
    AppContentCard {
        Text(
            text = stringResource(R.string.category_directory_default_title),
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            text = stringResource(R.string.category_directory_default_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
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
    onDelete: (CategoryPreference) -> Unit,
) {
    AppContentCard(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = stringResource(R.string.category_directory_custom_title),
            style = MaterialTheme.typography.titleMedium,
        )
        when {
            state.loading -> Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator()
            }
            state.loadFailed -> CategoryLoadFailed(onRetry = onRetry)
            state.customCategories.isEmpty() -> Text(
                text = stringResource(R.string.category_directory_custom_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            else -> state.customCategories.forEachIndexed { index, category ->
                CategoryPreferenceRow(
                    category = category,
                    canModify = state.canModify,
                    busy = state.busyCategoryId != null,
                    showDivider = index < state.customCategories.lastIndex,
                    onDelete = { onDelete(category) },
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
        Button(onClick = onRetry) {
            Text(stringResource(R.string.category_directory_retry))
        }
    }
}

@Composable
private fun CategoryPreferenceRow(
    category: CategoryPreference,
    canModify: Boolean,
    busy: Boolean,
    showDivider: Boolean,
    onDelete: () -> Unit,
) {
    AppListRow(showDivider = showDivider) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = category.name,
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = stringResource(R.string.category_directory_usage_count, category.usageCount),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (canModify) {
                IconButton(
                    enabled = !busy,
                    onClick = onDelete,
                ) {
                    Icon(
                        imageVector = Icons.Filled.DeleteOutline,
                        contentDescription = stringResource(
                            R.string.category_directory_delete_description,
                            category.name,
                        ),
                    )
                }
            }
        }
    }
}

@Composable
private fun CategoryDeleteDialog(
    category: CategoryPreference,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.category_directory_delete_title, category.name)) },
        text = { Text(stringResource(R.string.category_directory_delete_body)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(stringResource(R.string.category_directory_delete_confirm))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}
