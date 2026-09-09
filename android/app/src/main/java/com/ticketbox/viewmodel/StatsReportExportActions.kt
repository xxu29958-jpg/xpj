package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

fun StatsReportsViewModel.exportReport() {
    val repo = reportsRepository ?: return
    val state = uiState.value
    val binding = state.binding ?: return
    if (state.exporting || state.exportFile != null) return
    val query = currentExportQuery() ?: return
    val exportId = java.util.UUID.randomUUID().toString()
    _uiState.update { it.copy(exporting = true, exportId = exportId, exportMessage = null) }
    viewModelScope.launch {
        val result = repo.exportReportsOverviewCsv(query, binding)
        if (uiState.value.exportId != exportId || uiState.value.binding != binding || repo.dashboardAccess()?.binding != binding) return@launch
        _uiState.update { it.copy(exporting = false, exportFile = result.getOrNull(), exportId = exportId.takeIf { result.isSuccess },
            exportMessage = result.exceptionOrNull()?.toUiText(R.string.reports_export_failed)) }
    }
}

fun StatsReportsViewModel.takeExport(binding: LogicalSessionBinding, exportId: String? = uiState.value.exportId): CsvExport? {
    if (uiState.value.exportId != exportId) return null
    if (uiState.value.binding != binding || reportsRepository?.dashboardAccess()?.binding != binding) return null
    val file = uiState.value.exportFile
    _uiState.update { it.copy(exportFile = null, exportId = null, exportDestinationPending = false) }
    return file
}

fun StatsReportsViewModel.finishExport(message: UiText) {
    _uiState.update { it.copy(exportFile = null, exportId = null, exportDestinationPending = false, exportMessage = message) }
}

fun StatsReportsViewModel.exportLaunchHandled() {
    _uiState.update { it.copy(exportDestinationPending = true) }
}
