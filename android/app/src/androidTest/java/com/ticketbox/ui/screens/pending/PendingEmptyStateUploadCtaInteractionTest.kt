package com.ticketbox.ui.screens.pending

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Pins the empty Inbox's primary upload action to the existing image-picker callback. */
class PendingEmptyStateUploadCtaInteractionTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun tappingUploadInvokesTheImagePickerCallback() {
        var uploadRequests = 0
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                EmptyPendingState(
                    state = EmptyPendingStateModel(
                        uploading = false,
                        readOnly = false,
                        showUploadGuide = false,
                    ),
                    onUploadScreenshot = { uploadRequests += 1 },
                    onToggleGuide = {},
                    onRefresh = {},
                )
            }
        }

        composeRule.onNodeWithText("上传小票").performClick()

        composeRule.runOnIdle { assertEquals(1, uploadRequests) }
    }
}
