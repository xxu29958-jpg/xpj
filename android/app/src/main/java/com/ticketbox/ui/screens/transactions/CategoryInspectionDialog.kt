package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CategoryReference
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.CategoryDirectoryUiState
import com.ticketbox.viewmodel.CategoryDirectoryViewModel

@Composable
internal fun CategoryInspectionDialog(
    state: CategoryDirectoryUiState,
    viewModel: CategoryDirectoryViewModel,
    onOpenReference: (CategoryReference) -> Unit,
) {
    val category = state.inspectingCategory ?: return
    val inspection = state.inspection
    val busy = state.busyCategoryId != null
    AlertDialog(
        onDismissRequest = { if (!busy) viewModel.dismissInspection() },
        title = { Text(stringResource(R.string.category_directory_inspection_title, category.name)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.category_directory_usage_count, category.usageCount))
                Text(stringResource(R.string.category_directory_delete_body))
                if (state.inspectionLoading) CircularProgressIndicator()
                AppStatusBanner(message = state.inspectionError, tone = MessageTone.Danger)
                if (state.inspectionError != null) {
                    TextButton(enabled = !busy, onClick = { viewModel.inspect(category) }) {
                        Text(stringResource(R.string.category_directory_inspection_retry))
                    }
                }
                if (inspection != null) {
                    Text(stringResource(if (inspection.references.isEmpty())
                        R.string.category_directory_no_references else R.string.category_directory_references))
                    inspection.references.forEach { reference ->
                        TextButton(enabled = !busy, onClick = {
                            viewModel.dismissInspection()
                            onOpenReference(reference)
                        }) { Text(reference.label) }
                    }
                }
                if (!state.canModify) Text(stringResource(R.string.category_directory_readonly))
            }
        },
        confirmButton = {
            if (state.canModify && inspection != null && inspection.references.isEmpty()) {
                TextButton(enabled = !busy && !state.inspectionLoading,
                    onClick = { viewModel.delete(inspection.category) }) {
                    Text(stringResource(R.string.category_directory_delete_confirm))
                }
            }
        },
        dismissButton = {
            TextButton(enabled = !busy, onClick = viewModel::dismissInspection) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}
