package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppLoadingState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel

@Composable
internal fun SpendingGoalDetailScreen(
    viewModel: SpendingGoalDetailViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val goal = state.goal
    val navigateBack = if (state.isEditing) viewModel::cancelEdit else onBack
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = goal?.name ?: stringResource(R.string.spending_goal_detail_title),
            subtitle = goal?.let {
                stringResource(
                    R.string.spending_goal_detail_subtitle,
                    displayMonthLabel(it.month),
                    it.category ?: stringResource(R.string.spending_goal_scope_all),
                )
            },
            backText = stringResource(R.string.spending_goal_detail_back),
            onBack = navigateBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = state.isLoading,
            onRefresh = {
                if (!state.isEditing && !state.isSaving && !state.isArchiving) {
                    viewModel.load()
                }
            },
        ),
        slots = AppSecondaryPageSlots(
            status = { SpendingGoalDetailStatus(state) },
            bottomBar = if (goal != null && state.canModify && !goal.isArchived) {
                { SpendingGoalDetailFooter(state = state, viewModel = viewModel) }
            } else {
                null
            },
        ),
    ) {
        item {
            SpendingGoalDetailBody(
                state = state,
                viewModel = viewModel,
            )
        }
    }
    if (state.showArchiveDialog) {
        SpendingGoalArchiveDialog(state = state, viewModel = viewModel)
    }
}

@Composable
private fun SpendingGoalDetailStatus(state: SpendingGoalDetailUiState) {
    androidx.compose.foundation.layout.Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppDataAuthorityStrip(
            tone = when {
                !state.canModify -> DataAuthorityTone.ReadOnly
                state.isLoading || state.isSaving || state.isArchiving -> DataAuthorityTone.Refreshing
                else -> DataAuthorityTone.Backend
            },
        )
        if (!state.canModify) {
            AppStatusBanner(
                message = UiText.res(R.string.common_readonly_ledger),
                tone = MessageTone.Info,
                announceUpdates = false,
            )
        }
        state.message?.let {
            AppStatusBanner(message = it, tone = state.messageTone)
        }
        state.formError?.let {
            AppStatusBanner(message = it, tone = MessageTone.Danger)
        }
    }
}

@Composable
private fun SpendingGoalDetailBody(
    state: SpendingGoalDetailUiState,
    viewModel: SpendingGoalDetailViewModel,
) {
    when {
        state.isLoading && state.goal == null -> AppLoadingState(
            title = stringResource(R.string.spending_goal_detail_loading_title),
            body = stringResource(R.string.spending_goal_detail_loading_body),
        )
        state.loadError != null && state.goal == null -> AppErrorState(
            title = stringResource(R.string.spending_goal_detail_error_title),
            body = state.loadError.asString().ifBlank {
                stringResource(R.string.spending_goal_detail_load_failed)
            },
            onRetry = { viewModel.load() },
        )
        state.goal == null -> AppErrorState(
            title = stringResource(R.string.spending_goal_detail_error_title),
            body = stringResource(R.string.spending_goal_detail_load_failed),
            onRetry = { viewModel.load() },
        )
        state.isEditing -> SpendingGoalEditContent(state = state, viewModel = viewModel)
        else -> SpendingGoalViewContent(
            goal = state.goal,
            canModify = state.canModify,
            onArchive = viewModel::requestArchive,
        )
    }
}

@Composable
private fun SpendingGoalDetailFooter(
    state: SpendingGoalDetailUiState,
    viewModel: SpendingGoalDetailViewModel,
) {
    AppFloatingActionBar {
        if (state.isEditing) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                AppSecondaryButton(
                    text = stringResource(R.string.spending_goal_edit_cancel),
                    modifier = Modifier.weight(1f),
                    enabled = !state.isSaving,
                    leadingIcon = Icons.Filled.Close,
                    onClick = viewModel::cancelEdit,
                )
                AppPrimaryButton(
                    text = if (state.isSaving) {
                        stringResource(R.string.spending_goal_edit_saving)
                    } else {
                        stringResource(R.string.spending_goal_edit_save)
                    },
                    icon = Icons.Filled.Check,
                    modifier = Modifier.weight(1f),
                    enabled = state.canSave,
                    onClick = viewModel::save,
                )
            }
        } else {
            AppPrimaryButton(
                text = stringResource(R.string.spending_goal_edit_action),
                icon = Icons.Filled.Edit,
                modifier = Modifier.fillMaxWidth(),
                // R14-5：账本币种未确认时禁入编辑（回填币种必须与 save 同源，VM 同门兜底）。
                enabled = state.ledgerCurrency != null,
                onClick = viewModel::beginEdit,
            )
        }
    }
}

@Composable
private fun SpendingGoalArchiveDialog(
    state: SpendingGoalDetailUiState,
    viewModel: SpendingGoalDetailViewModel,
) {
    AlertDialog(
        onDismissRequest = viewModel::dismissArchive,
        title = { Text(stringResource(R.string.spending_goal_archive_dialog_title)) },
        text = { Text(stringResource(R.string.spending_goal_archive_dialog_body)) },
        confirmButton = {
            TextButton(
                enabled = !state.isArchiving,
                onClick = viewModel::archive,
            ) {
                Text(
                    if (state.isArchiving) {
                        stringResource(R.string.spending_goal_archiving)
                    } else {
                        stringResource(R.string.spending_goal_archive_confirm)
                    },
                )
            }
        },
        dismissButton = {
            TextButton(
                enabled = !state.isArchiving,
                onClick = viewModel::dismissArchive,
            ) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}
