package com.ticketbox.ui.screens

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import androidx.compose.ui.unit.Density
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.FundsViewModel
import kotlinx.coroutines.cancel

/** Shows the real funds screen over [FundsEditorFixture] and moves through it the way a person would. */
internal class FundsEditorDriver(private val compose: ComposeContentTestRule) : AutoCloseable {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    val fixture = FundsEditorFixture(context)
    lateinit var vm: FundsViewModel
        private set

    fun show(skin: AppSkin = AppSkin.Paper, fontScale: Float = 1f, expenseId: Long? = null) {
        vm = fixture.model(expenseId)
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale),
                LocalFundsRepository provides fixture.repository) {
                TicketboxTheme(skin = skin) { FundsScreen(vm, onBack = {}, onExpense = {}) }
            }
        }
        compose.waitUntil(10_000) { vm.state.value.accounts.isNotEmpty() && !vm.state.value.loading }
    }

    fun openAccount(id: String) {
        compose.runOnIdle { vm.open(id) }
        compose.waitUntil(10_000) { vm.state.value.detail?.publicId == id &&
            (vm.state.value.detail?.kind != "credit" || vm.state.value.installments != null) }
    }

    fun awaitEditor(mode: String) {
        compose.waitUntil(10_000) { vm.state.value.editing && vm.state.value.task.input?.mode == mode }
        compose.waitForIdle()
    }

    /** Leave the unsubmitted input the way a person would, so the next form starts clean. */
    fun abandon() {
        compose.onNodeWithText(text(R.string.funds_abandon_input)).performClick()
        compose.waitUntil(10_000) { vm.state.value.task.input == null && !vm.state.value.busy }
    }

    /** Bring the end of the form, where the change summary sits, right above the bottom bar. */
    fun scrollToEnd() {
        compose.onNode(hasScrollToIndexAction()).performTouchInput { repeat(8) { swipeUp() } }
        compose.waitForIdle()
    }

    fun field(label: String) = compose.onNode(hasSetTextAction() and hasText(label))

    fun capture(name: String) {
        compose.waitForIdle()
        saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())
    }

    fun text(resource: Int, vararg args: Any): String = context.getString(resource, *args)

    override fun close() {
        if (::vm.isInitialized) compose.runOnIdle { vm.viewModelScope.cancel() }
        fixture.close()
    }
}
