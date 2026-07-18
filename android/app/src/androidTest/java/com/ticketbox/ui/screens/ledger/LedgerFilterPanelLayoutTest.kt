package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.LedgerUiState
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

class LedgerFilterPanelLayoutTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun monthLabelDoesNotOverflowAcrossSingleColumnWidths() {
        var viewportWidth by mutableStateOf(AppAdaptiveBreakpoints.pairedActionInlineMinWidth)
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                Box(
                    modifier = Modifier
                        .width(viewportWidth)
                        .padding(horizontal = AppSpacing.cardPaddingSmall),
                ) {
                    LedgerFilterPanel(
                        state = LedgerUiState(monthFilter = "2026-07"),
                        actions = LedgerFilterPanelActions(
                            onOpenMonthPicker = {},
                            onOpenTools = {},
                            onManualAdd = {},
                            onMonthChange = {},
                        ),
                    )
                }
            }
        }

        val widths = listOf(
            AppAdaptiveBreakpoints.pairedActionInlineMinWidth,
            AppAdaptiveBreakpoints.contentActionInlineMinWidth,
            AppAdaptiveBreakpoints.mediumWidthMin - 1.dp,
        )
        widths.forEach { width ->
            composeRule.runOnIdle { viewportWidth = width }
            composeRule.waitForIdle()

            val textLayouts = mutableListOf<TextLayoutResult>()
            composeRule.onNodeWithText("2026.07")
                .assertIsDisplayed()
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { readLayout ->
                    readLayout(textLayouts)
                }

            assertFalse(
                "Expected the complete 2026.07 month label at $width without ellipsis",
                textLayouts.single().hasVisualOverflow,
            )
            composeRule.onNodeWithText("工具").assertIsDisplayed()
            composeRule.onNodeWithText("记一笔").assertIsDisplayed()
        }
    }
}
