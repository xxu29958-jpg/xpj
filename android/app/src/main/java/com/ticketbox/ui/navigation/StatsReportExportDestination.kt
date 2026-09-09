package com.ticketbox.ui.navigation

import android.content.ActivityNotFoundException
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.StatsReportsUiState
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.exportLaunchHandled
import com.ticketbox.viewmodel.finishExport
import com.ticketbox.viewmodel.takeExport

@Composable
internal fun StatsReportExportDestination(vm: StatsReportsViewModel, state: StatsReportsUiState) {
    val context = LocalContext.current
    var launchedId by rememberSaveable { mutableStateOf<String?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        val current = vm.uiState.value
        if (current.exportId != launchedId) return@rememberLauncherForActivityResult
        val binding = current.binding ?: return@rememberLauncherForActivityResult
        val file = vm.takeExport(binding, launchedId)
        if (uri == null) vm.finishExport(UiText.res(R.string.reports_export_cancelled))
        else if (file == null) vm.finishExport(UiText.res(R.string.reports_export_failed))
        else writeCsvExport(context, uri, file) { ok ->
            vm.finishExport(UiText.res(if (ok) R.string.reports_export_saved else R.string.reports_export_failed))
        }
    }
    LaunchedEffect(state.exportId, state.exportFile) {
        val file = state.exportFile ?: return@LaunchedEffect
        if (state.exportDestinationPending) return@LaunchedEffect
        launchedId = state.exportId
        vm.exportLaunchHandled()
        try { launcher.launch(file.fileName) } catch (_: ActivityNotFoundException) {
            vm.finishExport(UiText.res(R.string.reports_export_failed))
        }
    }
}
