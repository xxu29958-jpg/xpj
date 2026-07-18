package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.DebtGoalUiState
import com.ticketbox.viewmodel.DebtGoalViewModel

/**
 * Full replacement editor for a debt goal's linked debts.
 *
 * Existing non-voided links arrive preselected; open debts may be added, and a selected cleared
 * debt remains visible so the user can explicitly retain or remove it. The ViewModel enforces the
 * at-least-one invariant again at mutation time.
 */
@Composable
internal fun DebtGoalLinkEditorScreen(
    state: DebtGoalUiState,
    currency: CurrencyDisplay,
    viewModel: DebtGoalViewModel,
    onBack: () -> Unit,
) {
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.debt_goal_link_editor_title),
            subtitle = state.selectedGoal?.name,
            backText = stringResource(R.string.debt_goal_link_editor_back),
            onBack = onBack.takeUnless { state.isSubmitting },
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoadingLinkCandidates,
                hasReadableData = state.linkCandidates.isNotEmpty(),
            ),
            onRefresh = viewModel.linkEditor::refresh,
        ),
        slots = AppSecondaryPageSlots(
            status = { DebtGoalLinkEditorStatus(state) },
            bottomBar = {
                DebtGoalLinkEditorFooter(
                    state = state,
                    onSave = viewModel.linkEditor::save,
                )
            },
        ),
    ) {
        item {
            DebtGoalLinkEditorPicker(state, currency, viewModel)
        }
    }
}

@Composable
private fun DebtGoalLinkEditorPicker(
    state: DebtGoalUiState,
    currency: CurrencyDisplay,
    viewModel: DebtGoalViewModel,
) {
    DebtGoalOpenSection(
        title = stringResource(R.string.debt_goal_link_editor_picker_title),
        subtitle = stringResource(R.string.debt_goal_link_editor_picker_subtitle),
    ) {
        AppListStateContent(
            state = AppListStateSpec(
                isEmpty = state.linkCandidates.isEmpty(),
                loading = state.isLoadingLinkCandidates,
                emptyText = stringResource(R.string.debt_goal_link_editor_empty_body),
                emptyTitle = stringResource(R.string.debt_goal_link_editor_empty_title),
                emptyBody = stringResource(R.string.debt_goal_link_editor_empty_body),
            ),
        ) {
            state.linkCandidates.forEachIndexed { index, debt ->
                DebtPickerRow(
                    debt = debt,
                    selected = debt.publicId in state.selectedDebtIds,
                    currency = currency,
                    onToggle = if (state.isSubmitting || state.isLoadingLinkCandidates) {
                        null
                    } else {
                        { viewModel.linkEditor.toggle(debt.publicId) }
                    },
                    showDivider = index < state.linkCandidates.lastIndex,
                )
            }
        }
    }
}

@Composable
private fun DebtGoalLinkEditorStatus(state: DebtGoalUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppDataAuthorityStrip(
            tone = if (state.isLoadingLinkCandidates) {
                DataAuthorityTone.Refreshing
            } else {
                DataAuthorityTone.Backend
            },
        )
        state.error?.let { error ->
            AppStatusBanner(message = error, tone = MessageTone.Danger)
        }
    }
}

@Composable
private fun DebtGoalLinkEditorFooter(
    state: DebtGoalUiState,
    onSave: () -> Unit,
) {
    AppFloatingActionBar {
        Text(
            text = stringResource(
                R.string.debt_goal_link_editor_selected_count,
                state.selectedDebtIds.size,
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        AppPrimaryButton(
            text = if (state.isSubmitting) {
                stringResource(R.string.debt_goal_link_editor_saving)
            } else {
                stringResource(R.string.debt_goal_link_editor_save)
            },
            icon = Icons.Filled.Check,
            modifier = Modifier.fillMaxWidth(),
            enabled = state.canModify &&
                state.linkCandidates.isNotEmpty() &&
                state.selectedDebtIds.isNotEmpty() &&
                !state.isLoadingLinkCandidates &&
                state.isLinkEditorSnapshotFresh &&
                state.linkEditorSnapshotRowVersion == state.selectedGoal?.rowVersion &&
                !state.isSubmitting,
            onClick = onSave,
        )
    }
}
