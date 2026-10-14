package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryReference
import com.ticketbox.domain.model.CategoryReferenceKind
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.viewmodel.CategoryDirectoryUiState
import com.ticketbox.viewmodel.CategoryDirectoryViewModel

@Composable
internal fun CategoryInspectionScreen(
    state: CategoryDirectoryUiState,
    viewModel: CategoryDirectoryViewModel,
    onOpenReference: (CategoryReference) -> Unit,
) {
    val category = state.inspectingCategory ?: return
    val inspection = state.inspection
    val busy = state.busyCategoryId != null
    AppSecondaryScrollableColumn(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.category_directory_inspection_title, category.name),
            subtitle = stringResource(R.string.category_directory_delete_body),
            backText = stringResource(R.string.category_directory_title),
            onBack = { if (!busy) viewModel.dismissInspection() },
        ),
        slots = AppSecondaryPageSlots(
            status = { AppStatusBanner(message = state.inspectionError, tone = MessageTone.Danger) },
            bottomBar = { CategoryInspectionActions(state, viewModel) },
        ),
    ) {
        Text(stringResource(R.string.category_directory_usage_count, category.usageCount))
        if (state.inspectionLoading) CircularProgressIndicator()
        if (inspection != null) {
            Text(stringResource(if (inspection.references.isEmpty())
                R.string.category_directory_no_references else R.string.category_directory_references))
            inspection.references.forEach { reference ->
                SettingsEntryRow(
                    title = reference.label,
                    subtitle = stringResource(R.string.category_directory_reference_open),
                    icon = when (reference.kind) {
                        CategoryReferenceKind.Rule -> R.drawable.ic_lucide_wand_sparkles
                        CategoryReferenceKind.Budget -> R.drawable.ic_lucide_calendar_check
                        CategoryReferenceKind.SpendingGoal -> R.drawable.ic_lucide_target
                    },
                    onClick = if (busy) null else ({ viewModel.dismissInspection(); onOpenReference(reference) }),
                )
            }
        }
        if (!state.canModify) Text(stringResource(R.string.category_directory_readonly))
    }
}

@Composable
private fun CategoryInspectionActions(state: CategoryDirectoryUiState, viewModel: CategoryDirectoryViewModel) {
    val category = state.inspectingCategory ?: return
    val inspection = state.inspection
    val canRemove = state.canModify && inspection != null && inspection.references.isEmpty()
    AppFloatingActionBar {
        AppPrimaryButton(
            text = stringResource(if (canRemove) R.string.category_directory_delete_confirm
                else R.string.category_directory_inspection_retry),
            enabled = state.busyCategoryId == null && !state.inspectionLoading,
            onClick = { if (canRemove) viewModel.delete(inspection.category) else viewModel.inspect(category) },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
