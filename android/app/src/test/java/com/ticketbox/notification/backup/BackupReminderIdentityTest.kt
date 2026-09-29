package com.ticketbox.notification.backup

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.ServerBackupHealth
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.coroutines.test.runTest

class BackupReminderIdentityTest {
    @Test
    fun anotherServerStillGetsItsOwnBackupReminderAfterRebindingOnTheSameDay() = runTest {
        var activeServer = "https://first.example.test"
        var revision = "initial"
        val sent = mutableSetOf<String>()
        val requested = mutableListOf<String>()
        val notified = mutableListOf<String>()
        val engine = BackupStaleEngine(
            source = {
                requested += activeServer
                Result.success(ServerBackupHealth(latestBackupAt = null, ageHours = null, stale = true))
            },
            store = object : BackupStaleStore {
                override fun wasSent(key: String): Boolean = key in sent
                override fun markSent(key: String) { sent += key }
            },
            dispatcher = {
                notified += activeServer
                BackupStaleDispatchOutcome.SENT
            },
            runtime = BackupStaleRuntime(
                backupStaleAlertsEnabled = { true },
                activeBinding = { LogicalSessionBinding(activeServer, "", "owner", "session", revision) },
                today = { LocalDate.of(2026, 9, 30) },
            ),
        )

        engine.checkAndNotify()
        activeServer = "https://second.example.test"
        engine.checkAndNotify()
        revision = "refreshed-credential"
        engine.checkAndNotify()

        assertEquals(listOf("https://first.example.test", "https://second.example.test", "https://second.example.test"), requested)
        assertEquals(listOf("https://first.example.test", "https://second.example.test"), notified)
        assertEquals(2, sent.size)
    }

    @Test
    fun rebindingAfterTheHealthReadDoesNotPublishThePreviousServersResult() = runTest {
        val original = LogicalSessionBinding("https://first.example.test", "", "owner", "session", "revision")
        var current = original
        var notifications = 0
        val sent = mutableSetOf<String>()
        val engine = BackupStaleEngine(
            source = { Result.success(ServerBackupHealth(latestBackupAt = null, ageHours = null, stale = true)) },
            store = object : BackupStaleStore {
                override fun wasSent(key: String): Boolean {
                    current = original.copy(serverUrl = "https://second.example.test", sessionGeneration = "new-session")
                    return false
                }
                override fun markSent(key: String) { sent += key }
            },
            dispatcher = { notifications++; BackupStaleDispatchOutcome.SENT },
            runtime = BackupStaleRuntime({ true }, { current }, { LocalDate.of(2026, 9, 30) }),
        )

        assertEquals(BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_BINDING_CHANGED),
            engine.checkAndNotify())
        assertEquals(0, notifications)
        assertEquals(emptySet(), sent)
    }
}
