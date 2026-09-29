package com.ticketbox.ui.navigation

import android.content.ActivityNotFoundException
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.PortableExportActions
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.screens.settings.PortableExportPanel
import com.ticketbox.viewmodel.PortableExportViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun PortableExportDestination(exports: PortableExportActions) {
    val context = LocalContext.current.applicationContext
    val documents = remember(context) { PortableExportDocuments(context) }
    var recovery by remember { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(documents) { recovery = withContext(Dispatchers.IO) { documents.recoverInterrupted() } }
    val model: PortableExportViewModel = viewModel(factory = viewModelFactory {
        initializer { PortableExportViewModel(exports) }
    })
    val state by model.state.collectAsStateWithLifecycle()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        model.save(uri?.let(documents::document))
    }
    recovery?.let { removed ->
        AppStatusBanner(message = UiText.res(if (removed) R.string.portable_export_interrupted else R.string.portable_export_partial),
            tone = if (removed) MessageTone.Info else MessageTone.Danger)
    }
    PortableExportPanel(state, model, onSave = {
        if (model.chooseLocation()) {
            try { picker.launch("ticketbox-portable.zip") } catch (_: ActivityNotFoundException) { model.cancel() }
        }
    })
}
