package com.ticketbox.ui.components

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.design.stateTokensForSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * UI/UX 批 11: AppStatusBanner is the Android mirror of /web `.dt-alert` — the
 * unified settings-tree feedback surface. These pin (a) the VM-held
 * [MessageTone] maps to the right [com.ticketbox.ui.design.StateTone] color
 * triple across every skin, and (b) the banner renders a non-blank message and
 * stays silent for null / blank.
 *
 * Lives in androidTest (Compose render assertions need the device runtime); the
 * tone-mapping checks are pure and could be JVM, but are kept here so the whole
 * banner contract sits in one file and the @Test baseline (src/test only) is
 * untouched.
 */
class AppStatusBannerTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun toneMapsToMatchingStateToneForEverySkin() {
        for (skin in AppSkin.entries) {
            val tokens = stateTokensForSkin(skin)
            assertEquals(tokens.success, tokens.forTone(MessageTone.Success))
            assertEquals(tokens.danger, tokens.forTone(MessageTone.Danger))
            assertEquals(tokens.info, tokens.forTone(MessageTone.Info))
            assertEquals(tokens.neutral, tokens.forTone(MessageTone.Neutral))
        }
    }

    @Test
    fun nonBlankMessageRenders() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppStatusBanner(message = UiText.Raw("已保存"), tone = MessageTone.Success)
            }
        }

        composeRule.onNodeWithText("已保存").assertIsDisplayed()
    }

    @Test
    fun nullMessageRendersNothing() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppStatusBanner(message = null, tone = MessageTone.Success)
            }
        }

        composeRule.onNodeWithText("已保存").assertDoesNotExist()
    }

    @Test
    fun blankMessageRendersNothing() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppStatusBanner(message = UiText.Raw("   "), tone = MessageTone.Success)
            }
        }

        composeRule.onNodeWithText("   ").assertDoesNotExist()
    }
}
