package com.ticketbox.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.FontScale
import androidx.compose.ui.viewinterop.AndroidView

/** Dialog windows inherit their host View's Context, not an outer LocalDensity override. */
@OptIn(ExperimentalTestApi::class)
@Composable
internal fun PlatformFontScale(scale: Float, content: @Composable () -> Unit) {
    val currentContent by rememberUpdatedState(content)
    DeviceConfigurationOverride(DeviceConfigurationOverride.FontScale(scale)) {
        key(scale) {
            AndroidView(modifier = Modifier.fillMaxSize(), factory = { context ->
                ComposeView(context).apply { setContent { currentContent() } }
            })
        }
    }
}
