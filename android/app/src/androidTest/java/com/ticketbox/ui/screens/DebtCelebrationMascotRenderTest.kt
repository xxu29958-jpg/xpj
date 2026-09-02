package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.mascot.MascotController
import com.ticketbox.ui.mascot.MascotEvent
import com.ticketbox.ui.mascot.MascotState
import com.ticketbox.ui.mascot.MascotStateMachine
import com.ticketbox.ui.mascot.mascotArtRes
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtGoalCelebration
import com.ticketbox.viewmodel.DebtSettleCelebration
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

/**
 * W2-A production-consumer regression: both debt milestone overlays must drive the mascot
 * controller to Celebrating and therefore resolve the theme-specific celebrating image.
 */
class DebtCelebrationMascotRenderTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun debtSettleRendersCelebratingMascotInPaper() {
        render(CelebrationKind.Settle, AppSkin.Paper)
    }

    @Test
    fun debtSettleRendersCelebratingMascotInMidnight() {
        render(CelebrationKind.Settle, AppSkin.Midnight)
    }

    @Test
    fun debtGoalRendersCelebratingMascotInPaper() {
        render(CelebrationKind.Goal, AppSkin.Paper)
    }

    @Test
    fun debtGoalRendersCelebratingMascotInMidnight() {
        render(CelebrationKind.Goal, AppSkin.Midnight)
    }

    private fun render(kind: CelebrationKind, skin: AppSkin) {
        val controller = MascotController(MascotStateMachine()) { 0L }
        var consumed = false
        composeRule.mainClock.autoAdvance = false
        composeRule.setContent {
            TicketboxTheme(skin = skin, reduceMotion = true) {
                Box(Modifier.fillMaxSize()) {
                    when (kind) {
                        CelebrationKind.Settle -> DebtSettleCelebrationOverlay(
                            celebration = DebtSettleCelebration(counterpartyLabel = "小敏"),
                            mascot = controller,
                            onConsume = { consumed = true },
                        )
                        CelebrationKind.Goal -> DebtGoalCelebrationOverlay(
                            celebration = DebtGoalCelebration(goalName = "还清欠款"),
                            mascot = controller,
                            onConsume = { consumed = true },
                        )
                    }
                }
            }
        }

        composeRule.mainClock.advanceTimeBy(500L)
        composeRule.waitForIdle()

        val announce = InstrumentationRegistry.getInstrumentation().targetContext.getString(
            when (kind) {
                CelebrationKind.Settle -> R.string.debt_settle_celebration_announce
                CelebrationKind.Goal -> R.string.debt_plan_celebration_announce
            },
        )
        composeRule.onNodeWithContentDescription(announce).assertExists()
        assertEquals(MascotState.Celebrating, controller.state)
        assertEquals(expectedCelebratingAsset(skin), mascotArtRes(controller.state, skin))
        assertFalse(consumed)
    }

    private fun expectedCelebratingAsset(skin: AppSkin): Int = when (skin) {
        AppSkin.Paper -> R.drawable.mascot_celebrating_paper
        AppSkin.Midnight -> R.drawable.mascot_celebrating_midnight
    }

    private enum class CelebrationKind { Settle, Goal }
}
