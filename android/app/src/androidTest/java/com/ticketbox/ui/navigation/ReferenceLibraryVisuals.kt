package com.ticketbox.ui.navigation

import android.content.Context
import android.graphics.Bitmap
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.compose.ui.unit.Density
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.File

@Composable
internal fun ReferenceLibraryTestTheme(content: @Composable () -> Unit) {
    val large = InstrumentationRegistry.getArguments().getString("visualMode") == "large"
    CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, if (large) 2f else 1f)) {
        TicketboxTheme(skin = if (large) AppSkin.Midnight else AppSkin.Default, content = content)
    }
}

internal fun captureReferenceLibraryStep(rule: ComposeTestRule, context: Context, name: String) {
    val prefix = InstrumentationRegistry.getArguments().getString("visualCapture") ?: return
    rule.waitForIdle()
    val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
    File(context.getExternalFilesDir(null), "$prefix-$name.png").outputStream().use {
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
    }
}
