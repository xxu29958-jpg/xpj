package com.ticketbox.ui.appearance.background

import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.BackgroundEditorActions
import com.ticketbox.ui.screens.settings.BackgroundEditorScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.BackgroundEditorState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class BackgroundEditorViewportTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun compositionUsesTheGlobalCanvasEvenUnderTheLocalUnlockBanner() {
        compose.runOnUiThread { compose.activity.enableEdgeToEdge() }
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                Box(Modifier.fillMaxSize().testTag("applied-viewport")) {
                    ImmersiveBackgroundScaffold(BackgroundSettings(), AppSkin.Paper, SurfaceRole.Settings) {
                        // Same existing shell constraints: advisory banner, then weighted body.
                        Column(Modifier.fillMaxSize()) {
                            AppStatusBanner(
                                message = UiText.res(R.string.app_local_unlock_disabled_banner),
                                tone = MessageTone.Info,
                                modifier = Modifier.statusBarsPadding().padding(
                                    horizontal = AppSpacing.screenHorizontal,
                                    vertical = AppSpacing.compactGap,
                                ),
                            )
                            Box(Modifier.weight(1f)) {
                                BackgroundEditorScreen(
                                    editor = BackgroundEditorState(BackgroundSettings()),
                                    currentSkin = AppSkin.Paper,
                                    actions = BackgroundEditorActions({}, {}, {}),
                                )
                            }
                        }
                    }
                }
            }
        }

        val applied = compose.onNodeWithTag("applied-viewport").fetchSemanticsNode().boundsInWindow
        val preview = compose.onNodeWithTag("background-editor-viewport").fetchSemanticsNode().boundsInWindow
        assertEquals("Preview left origin", applied.left, preview.left, 1f)
        assertEquals("Preview top origin", applied.top, preview.top, 1f)
        assertEquals("Preview canvas width", applied.width, preview.width, 1f)
        assertEquals("Preview canvas height", applied.height, preview.height, 1f)
    }
}
