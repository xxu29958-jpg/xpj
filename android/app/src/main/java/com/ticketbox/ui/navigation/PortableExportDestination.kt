package com.ticketbox.ui.navigation

import android.content.ActivityNotFoundException
import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.PortableExportActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.ui.screens.settings.PortableExportPanel
import com.ticketbox.viewmodel.PortableExportDestination
import com.ticketbox.viewmodel.PortableExportViewModel
import java.io.OutputStream

@Composable
internal fun PortableExportDestination(exports: PortableExportActions) {
    val resolver = LocalContext.current.applicationContext.contentResolver
    val model: PortableExportViewModel = viewModel(factory = viewModelFactory {
        initializer { PortableExportViewModel(exports) }
    })
    val state by model.state.collectAsStateWithLifecycle()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        model.save(uri?.let { SystemExportDocument(resolver, it) })
    }
    PortableExportPanel(state, model, onSave = {
        if (model.chooseLocation()) {
            try { picker.launch("ticketbox-portable.zip") } catch (_: ActivityNotFoundException) { model.cancel() }
        }
    })
}

private class SystemExportDocument(private val resolver: ContentResolver, private val uri: Uri) : PortableExportDestination {
    override fun open(): OutputStream = try {
        resolver.openOutputStream(uri, "wt") ?: throw RepositoryException("无法写入所选位置，请重新选择。")
    } catch (error: SecurityException) {
        throw RepositoryException("无法写入所选位置，请重新选择。", cause = error)
    }

    override fun discard(): Boolean = DocumentsContract.deleteDocument(resolver, uri)
}
