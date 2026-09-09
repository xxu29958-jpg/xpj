package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import com.ticketbox.domain.model.CsvExport

internal fun writeCsvExport(
    context: Context,
    uri: Uri,
    exportFile: CsvExport,
    onResult: (Boolean) -> Unit,
) {
    runCatching {
        context.contentResolver.openOutputStream(uri)?.use { output ->
            output.write(exportFile.bytes)
        } ?: error("Output stream is null")
    }
        .onSuccess { onResult(true) }
        .onFailure { onResult(false) }
}
