package com.ticketbox.ui.navigation

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.ui.screens.expense.OriginalAttachmentPanel
import com.ticketbox.upload.readReplenishmentOriginal
import com.ticketbox.viewmodel.OriginalAttachmentViewModel
import com.ticketbox.viewmodel.beginSelection
import com.ticketbox.viewmodel.resumeSelectedSource
import com.ticketbox.viewmodel.selectedSource

/** Both pending editing and confirmed facts continue the same original task on their existing bill. */
@Composable
internal fun OriginalAttachmentRoute(expenseId: Long, screenFactory: MainScreenFactory, onAccepted: () -> Unit = {}) {
    val originals = screenFactory.repositories.originalAttachments ?: return
    val context = LocalContext.current.applicationContext
    val vm: OriginalAttachmentViewModel = viewModel(key = "original-$expenseId", factory = viewModelFactory {
        initializer { OriginalAttachmentViewModel(expenseId, originals, screenFactory.repository::fetchImage, createSavedStateHandle()) }
    })
    val state by vm.state.collectAsStateWithLifecycle()
    val prepare: suspend (String) -> com.ticketbox.upload.PreparedUploadImage? = { context.readReplenishmentOriginal(Uri.parse(it)) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { runCatching { context.contentResolver.takePersistableUriPermission(it, Intent.FLAG_GRANT_READ_URI_PERMISSION) } }
        vm.selectedSource(uri?.toString())
        vm.resumeSelectedSource(prepare)
    }
    LaunchedEffect(state.deliveredRevision) { if (state.deliveredRevision > 0) onAccepted() }
    LaunchedEffect(state.access?.binding) { vm.resumeSelectedSource(prepare) }
    OriginalAttachmentPanel(state, vm, onSelectFile = {
        if (vm.beginSelection()) picker.launch(arrayOf("image/*"))
    }, onResumeSelection = { vm.resumeSelectedSource(prepare) })
}
