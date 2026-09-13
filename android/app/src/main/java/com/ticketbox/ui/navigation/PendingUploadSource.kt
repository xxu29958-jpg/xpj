package com.ticketbox.ui.navigation

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import com.ticketbox.upload.PreparedUploadImage
import com.ticketbox.upload.prepareScreenshotUpload
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Retain the application resolver, never the Activity, while a batch is paused. */
internal fun pendingUploadSource(context: Context): suspend (String) -> PreparedUploadImage? {
    val applicationContext = context.applicationContext
    return { imageRef ->
        withContext(Dispatchers.IO) {
            applicationContext.prepareScreenshotUpload(Uri.parse(imageRef))
        }
    }
}

/** The picker grants temporary access; retain it until the existing selection is accepted or cancelled. */
internal fun persistPickedUploadSource(context: Context, uri: Uri) {
    try {
        context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
    } catch (_: SecurityException) {
        // Foreground copying can still succeed. Only Room acceptance may claim the original is saved.
        Log.w("UploadSource", "The picker did not grant persistent read access")
    }
}

internal fun cancelPendingUploadSelection(context: Context, state: LaunchActionState) {
    val selection = state.pendingUpload?.selection ?: return
    state.cancelUploadSelection()
    releaseUploadSourceGrants(context, state, selection)
}

/** Another queued selection may still need the same URI; never release its read capability. */
internal fun releaseUploadSourceGrants(context: Context, state: LaunchActionState, selection: LaunchIntentRequest.ShareImages) {
    val resolver = context.contentResolver
    val held = resolver.persistedUriPermissions.filter { it.isReadPermission }.map { it.uri }.toSet()
    for (source in selection.uris.distinct().filterNot(state::referencesUploadSource)) {
        val uri = Uri.parse(source)
        if (uri !in held) continue
        try {
            resolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } catch (_: SecurityException) {
            Log.w("UploadSource", "A completed selection's read grant could not be released")
        }
    }
}
