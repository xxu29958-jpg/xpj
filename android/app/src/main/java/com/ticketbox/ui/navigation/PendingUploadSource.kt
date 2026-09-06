package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
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
