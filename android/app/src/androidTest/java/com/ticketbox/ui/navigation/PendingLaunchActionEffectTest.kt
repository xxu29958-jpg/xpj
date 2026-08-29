package com.ticketbox.ui.navigation

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.runtime.rememberCoroutineScope
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class PendingLaunchActionEffectTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun consumingSharedImagesDoesNotCancelDispatchedUpload() {
        val shellState = MainShellState()
        val started = CountDownLatch(1)
        val release = CompletableDeferred<Unit>()
        val cancelled = AtomicBoolean(false)
        val completed = AtomicBoolean(false)

        composeRule.setContent {
            val uploadScope = rememberCoroutineScope()
            PendingLaunchActionEffect(
                shellState = shellState,
                uploadScope = uploadScope,
                onOpenPicker = {},
                onUploadSharedImages = {
                    started.countDown()
                    try {
                        release.await()
                        completed.set(true)
                    } catch (error: CancellationException) {
                        cancelled.set(true)
                        throw error
                    }
                },
            )
        }

        composeRule.runOnIdle {
            shellState.launchAction.post(
                LaunchAction.UploadSharedImages(listOf("content://ticketbox/shared-receipt")),
            )
        }
        composeRule.waitForIdle()
        assertTrue("shared upload never started", started.await(5, TimeUnit.SECONDS))

        assertFalse("consuming the action cancelled its own upload", cancelled.get())

        release.complete(Unit)
        composeRule.waitUntil(timeoutMillis = 5_000) { completed.get() }
    }
}
