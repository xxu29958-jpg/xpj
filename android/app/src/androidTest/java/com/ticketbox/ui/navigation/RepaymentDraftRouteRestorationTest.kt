package com.ticketbox.ui.navigation

import androidx.compose.material3.Text
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

class RepaymentDraftRouteRestorationTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun focusedDraftArgumentSurvivesSavedInstanceStateRestore() {
        val restorationTester = StateRestorationTester(composeRule)
        lateinit var navigateToFocusedDraft: () -> Unit
        restorationTester.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                val navController = rememberNavController()
                navigateToFocusedDraft = {
                    navController.navigate(repaymentDraftRoute("draft-1"))
                }
                NavHost(navController = navController, startDestination = RESTORATION_START_ROUTE) {
                    composable(RESTORATION_START_ROUTE) {
                        Text("start")
                    }
                    composable(
                        route = REPAYMENT_DRAFT_ROUTE,
                        arguments = listOf(
                            navArgument(REPAYMENT_DRAFT_FOCUS_ARG) {
                                type = NavType.StringType
                                nullable = true
                                defaultValue = null
                            },
                        ),
                    ) { entry ->
                        Text(
                            text = entry.arguments?.getString(REPAYMENT_DRAFT_FOCUS_ARG).orEmpty(),
                            modifier = androidx.compose.ui.Modifier.testTag(FOCUSED_DRAFT_TAG),
                        )
                    }
                }
            }
        }

        composeRule.runOnIdle { navigateToFocusedDraft() }
        composeRule.onNodeWithTag(FOCUSED_DRAFT_TAG).assertTextEquals("draft-1")

        restorationTester.emulateSavedInstanceStateRestore()

        composeRule.onNodeWithTag(FOCUSED_DRAFT_TAG).assertTextEquals("draft-1")
    }

    private companion object {
        const val RESTORATION_START_ROUTE = "restoration-start"
        const val FOCUSED_DRAFT_TAG = "focused-repayment-draft"
    }
}
