package com.ticketbox.ui.components

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AppBackButtonTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun backButtonKeepsSingleSemanticLabelAndTouchHeight() {
        var clicks = 0
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppBackButton(
                    text = BACK_LABEL,
                    onClick = { clicks += 1 },
                )
            }
        }

        val button = composeRule.onNodeWithContentDescription(BACK_LABEL)
        button.assert(SemanticsMatcher.expectValue(SemanticsProperties.ContentDescription, listOf(BACK_LABEL)))
        assertDpAtLeast(expected = 48.dp, actual = button.getUnclippedBoundsInRoot().bottom - button.getUnclippedBoundsInRoot().top)

        button.performClick()

        assertEquals(1, clicks)
    }

    @Test
    fun destinationOnlyLabelIsAnnouncedAsGoingBack() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppBackButton(text = DESTINATION_LABEL, onClick = {})
            }
        }

        // Visible text stays short; TalkBack hears the action, not a bare noun.
        composeRule.onNodeWithText(DESTINATION_LABEL).assertExists()
        composeRule.onNodeWithContentDescription("返回$DESTINATION_LABEL")
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.ContentDescription, listOf("返回$DESTINATION_LABEL")))
    }

    private fun assertDpAtLeast(expected: Dp, actual: Dp) {
        assertTrue(
            "Expected back button touch height >= $expected, got $actual",
            actual.value + DP_EPSILON >= expected.value,
        )
    }

    private companion object {
        const val BACK_LABEL = "返回账本"
        const val DESTINATION_LABEL = "计划"
        const val DP_EPSILON = 0.01f
    }
}
