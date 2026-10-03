package com.ticketbox.ui.screens

import android.app.Activity
import android.content.Intent
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.core.app.ActivityOptionsCompat
import com.google.zxing.client.android.Intents
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

class BindingQrHandoffTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun scannerPrefillsBothFieldsAndRequiresExplicitBindWithoutLosingInputOnCancel() {
        val registry = ScanResultRegistry()
        val binds = mutableListOf<Pair<String, String>>()
        showScreen(registry, false, binds)
        compose.onNodeWithText("扫一扫连接").performClick()
        compose.runOnIdle {
            registry.reply(Activity.RESULT_OK, Intent().putExtra(Intents.Scan.RESULT,
                "https://family.example.com/web/auth/login#pairing=12345678"))
        }
        compose.onNodeWithText("绑定码").assertTextContains("12345678")
        compose.onNodeWithText("扫一扫连接").performScrollTo().performClick()
        compose.runOnIdle { registry.reply(Activity.RESULT_CANCELED, Intent()) }
        compose.onNodeWithText("绑定码").assertTextContains("12345678")
        compose.onNodeWithText("扫一扫连接").performScrollTo().performClick()
        compose.runOnIdle { registry.reply(Activity.RESULT_OK, Intent().putExtra(Intents.Scan.RESULT, "not a connection")) }
        compose.onNodeWithText("绑定码").assertTextContains("12345678")
        compose.runOnIdle { check(binds.isEmpty()) }
        compose.onNodeWithText("绑定账本").performScrollTo().performClick()
        compose.runOnIdle { check(binds.single() == ("https://family.example.com" to "12345678")) }
    }

    @Test
    fun pendingEnrollmentCannotBeReplacedByAnotherScan() {
        showScreen(ScanResultRegistry(), true, mutableListOf())
        compose.onNodeWithText("扫一扫连接").assertIsNotEnabled()
    }

    private fun showScreen(registry: ScanResultRegistry, pending: Boolean, binds: MutableList<Pair<String, String>>) {
        val owner = object : ActivityResultRegistryOwner { override val activityResultRegistry = registry }
        compose.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides owner) {
                TicketboxTheme(skin = AppSkin.Default) {
                    BindServerScreen(false, null, pending, ServerUrlEntryConfig("https://old.example.com", false),
                        BindServerActions(onBind = { server, code -> binds += server to code },
                            onJoinWithInvitation = {}, onAbandonPendingEnrollment = {}))
                }
            }
        }
    }
}

private class ScanResultRegistry : ActivityResultRegistry() {
    private var pendingRequest = 0
    override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>, input: I,
                                options: ActivityOptionsCompat?) { pendingRequest = requestCode }

    fun reply(resultCode: Int, intent: Intent) { dispatchResult(pendingRequest, resultCode, intent) }
}
