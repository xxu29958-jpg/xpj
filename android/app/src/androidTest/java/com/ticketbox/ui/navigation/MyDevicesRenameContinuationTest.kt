package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextReplacement
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DeviceRenameRequestDto
import com.ticketbox.data.remote.dto.MyDeviceDto
import com.ticketbox.data.remote.dto.MyDeviceListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.settings.MyDevicesScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.MyDevicesViewModel
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The real device screen, ViewModel and repository retain the edit until the server accepts it. */
class MyDevicesRenameContinuationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val requests = CopyOnWriteArrayList<Pair<String, String>>()
    @Volatile private var reject = true
    @Volatile private var device = MyDeviceDto("rename-device", "旧设备", "android", null, null, null, false)
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun ledgerDevices(ledgerId: String) = MyDeviceListResponseDto(listOf(device))
            override suspend fun renameLedgerDevice(ledgerId: String, publicId: String, request: DeviceRenameRequestDto): MyDeviceDto {
                requests += publicId to request.deviceName
                if (reject) throw IOException("controlled rename connection loss")
                return device.copy(deviceName = request.deviceName).also { device = it }
            }
        }
    }
    private val viewModel = MyDevicesViewModel(harness.screenFactory.ledgerRepository)

    @After fun close() {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun failedRenameKeepsTheRawInputAndRetryUpdatesTheSameDevice() {
        val large = InstrumentationRegistry.getArguments().getString("visualMode") == "large"
        compose.setContent {
            if (mounted.value) TicketboxTheme(skin = if (large) AppSkin.Midnight else AppSkin.Default) {
                MyDevicesScreen(viewModel, "correction-ledger", {}, {})
            }
        }
        compose.waitUntil(5_000) { viewModel.uiState.value.devices.size == 1 }
        compose.onNodeWithContentDescription(context.getString(com.ticketbox.R.string.my_devices_actions_content_description)).performClick()
        compose.onNodeWithText(context.getString(com.ticketbox.R.string.my_devices_action_rename)).performClick()
        val raw = "  家里备用手机  "
        compose.onNode(hasSetTextAction()).performTextReplacement(raw)
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(com.ticketbox.R.string.my_devices_rename_dialog_confirm)).performClick()
        compose.waitUntil(5_000) { requests.size == 1 && viewModel.uiState.value.busyDeviceId == null }
        compose.onNode(hasSetTextAction()).assertTextContains(raw)
        saveConsumerArtPreview("device-rename-failed-retained", compose.onRoot().captureToImage().asAndroidBitmap())
        assertEquals("旧设备", viewModel.uiState.value.devices.single().deviceName)
        reject = false
        compose.onNodeWithText(context.getString(com.ticketbox.R.string.my_devices_rename_dialog_confirm)).performClick()
        compose.waitUntil(5_000) { viewModel.uiState.value.devices.single().deviceName == raw.trim() }
        compose.onNode(hasSetTextAction()).assertDoesNotExist()
        assertEquals(listOf("rename-device" to raw.trim(), "rename-device" to raw.trim()), requests.toList())
    }
}
