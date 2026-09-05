package com.ticketbox.ui

import android.graphics.Bitmap
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.assertTrue

/** Existing interaction tests also publish their synthetic-state renders for visual review. */
internal fun saveConsumerArtPreview(name: String, bitmap: Bitmap) {
    // Gradle owns and copies this output directory. Direct IDE runs may omit it.
    val directory = InstrumentationRegistry.getArguments().getString("additionalTestOutputDir") ?: return
    val destination = File(directory, "ticketbox-art-$name.png")
    destination.parentFile?.mkdirs()
    destination.outputStream().use {
        assertTrue("Could not encode the real consumer screenshot", bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
    }
}
