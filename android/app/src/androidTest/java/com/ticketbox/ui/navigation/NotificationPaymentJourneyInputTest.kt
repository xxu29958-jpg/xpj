package com.ticketbox.ui.navigation

import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.TicketboxApplication
import com.ticketbox.notification.PaymentNotificationParser
import com.ticketbox.notification.PaymentNotificationSnapshot
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.notificationIdentityKey
import java.time.Instant
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Explicit cloud-journey input boundary, never a replacement AppContainer or API. */
class NotificationPaymentJourneyInputTest {
    @Test fun acceptControlledPaymentSamplesThroughTheInstalledApp() = runBlocking {
        assumeTrue(InstrumentationRegistry.getArguments().getString("ticketboxPaymentJourney") == "isolated-cloud")
        check(Build.PRODUCT.contains("sdk")) { "Payment journey requires its disposable emulator" }
        val context = ApplicationProvider.getApplicationContext<TicketboxApplication>()
        val container = context.container
        val binding = withTimeout(20_000) {
            var current = container.expenseRepository.captureDeferredLedgerBinding()
            while (current == null) { delay(100); current = container.expenseRepository.captureDeferredLedgerBinding() }
            current
        }
        val uri = java.net.URI(binding.serverUrl)
        check(uri.host == "127.0.0.1" && uri.port == 18880) { "Payment journey requires its isolated backend" }
        assertTrue("The actual settings screen must enable reminders", container.settingsStore.notificationPreferences().pendingDraftReminders)
        val whenPosted = Instant.parse("2026-09-01T04:00:00Z").toEpochMilli()
        val samples = listOf(
            "com.eg.android.AlipayGphone" to "花呗还款成功 ¥100.00",
            "com.jingdong.app.mall" to "白条还款成功 ¥80.00",
            "com.eg.android.AlipayGphone" to "支付成功 ¥16.80 收款方：瑞幸咖啡",
        )
        val originals = mutableMapOf<Int, Long>()
        repeat(2) {
            samples.forEachIndexed { index, (source, body) ->
                val snapshot = PaymentNotificationSnapshot(source, "支付通知", body, null, null, whenPosted + index)
                val parsed = requireNotNull(PaymentNotificationParser.parse(snapshot))
                val key = notificationIdentityKey("notification-consumer-$index", snapshot.postTimeMillis)
                val row = container.notificationCaptureRepository.accept(parsed, binding, key).getOrThrow()
                assertEquals("Repeated delivery must keep the original disk command", originals.getOrPut(index) { row }, row)
            }
        }
        container.outboxDrainEngine.drainOnce()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        withTimeout(20_000) {
            while (manager.activeNotifications.count { it.notification.channelId == TicketboxNotifier.CHANNEL_REPAYMENTS } != 2) delay(100)
        }
        assertEquals(2, manager.activeNotifications.count { it.notification.channelId == TicketboxNotifier.CHANNEL_REPAYMENTS })
        assertEquals(1, manager.activeNotifications.count { it.notification.channelId == TicketboxNotifier.CHANNEL_DRAFTS })
        // The Python consumer journey taps these real notifications after instrumentation exits.
    }
}
