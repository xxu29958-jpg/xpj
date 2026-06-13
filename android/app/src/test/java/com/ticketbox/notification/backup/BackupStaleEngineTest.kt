package com.ticketbox.notification.backup

import com.ticketbox.domain.model.ServerBackupHealth
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

/**
 * [BackupStaleEngine] 编排契约(轴6 备份超龄通知):前置门依次短路、stale 才投递、
 * 日级去重、SENT 才 markSent、source 失败映射 TransientFailure(worker retry)。
 * 全 fake 注入,纯 JVM 直测。
 */
class BackupStaleEngineTest {

    private class Harness(
        var healthResult: () -> Result<ServerBackupHealth> = {
            Result.success(ServerBackupHealth(latestBackupAt = "2026-06-10T00:00:00+00:00", ageHours = 72, stale = true))
        },
        var dispatchOutcome: BackupStaleDispatchOutcome = BackupStaleDispatchOutcome.SENT,
    ) {
        var enabled = true
        var sessionReady = true
        var today: LocalDate = LocalDate.of(2026, 6, 13)
        var sourceCalls = 0
        val dispatched = mutableListOf<BackupStaleDecision>()
        val sent = mutableSetOf<String>()

        val engine = BackupStaleEngine(
            source = {
                sourceCalls++
                healthResult()
            },
            store = object : BackupStaleStore {
                override fun wasSent(key: String): Boolean = key in sent
                override fun markSent(key: String) {
                    sent += key
                }
            },
            dispatcher = { decision ->
                dispatched += decision
                dispatchOutcome
            },
            runtime = BackupStaleRuntime(
                backupStaleAlertsEnabled = { enabled },
                sessionReady = { sessionReady },
                today = { today },
            ),
        )
    }

    @Test
    fun staleBackupDispatchesWithAgeAndMarksSent() = runTest {
        val harness = Harness()
        val outcome = harness.engine.checkAndNotify()
        assertEquals(BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SENT), outcome)
        assertEquals("v1:backup:2026-06-13", harness.dispatched.single().key)
        assertEquals(72, harness.dispatched.single().ageHours)
        assertTrue("v1:backup:2026-06-13" in harness.sent)
    }

    @Test
    fun disabledToggleShortCircuitsBeforeSource() = runTest {
        val harness = Harness()
        harness.enabled = false
        val outcome = harness.engine.checkAndNotify()
        assertEquals(BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_DISABLED), outcome)
        assertEquals(0, harness.sourceCalls)
    }

    @Test
    fun missingSessionShortCircuitsBeforeSource() = runTest {
        val harness = Harness()
        harness.sessionReady = false
        val outcome = harness.engine.checkAndNotify()
        assertEquals(BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_NO_SESSION), outcome)
        assertEquals(0, harness.sourceCalls)
    }

    @Test
    fun sourceFailureMapsToTransientFailureWithoutMarkSent() = runTest {
        // worker 据此 Result.retry();失败绝不 markSent(0046:失败安全降级)。
        val harness = Harness(healthResult = { Result.failure(RuntimeException("boom")) })
        val outcome = harness.engine.checkAndNotify()
        assertEquals(BackupStaleRunOutcome.TransientFailure("RuntimeException"), outcome)
        assertTrue(harness.sent.isEmpty())
        assertEquals(0, harness.dispatched.size)
    }

    @Test
    fun freshBackupDoesNotDispatch() = runTest {
        val harness = Harness(
            healthResult = {
                Result.success(ServerBackupHealth(latestBackupAt = "2026-06-13T00:00:00+00:00", ageHours = 3, stale = false))
            },
        )
        val outcome = harness.engine.checkAndNotify()
        assertEquals(BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_FRESH), outcome)
        assertEquals(0, harness.dispatched.size)
        assertTrue(harness.sent.isEmpty())
    }

    @Test
    fun alreadySentTodaySkipsDispatchButNextDayFiresAgain() = runTest {
        // 日级粒度契约:同一天去重,次日仍 stale 则再响(备份链断要催,区别于预算的一月一响)。
        val harness = Harness()
        harness.sent += "v1:backup:2026-06-13"
        assertEquals(
            BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_ALREADY_SENT),
            harness.engine.checkAndNotify(),
        )
        assertEquals(0, harness.dispatched.size)
        harness.today = LocalDate.of(2026, 6, 14)
        assertEquals(
            BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SENT),
            harness.engine.checkAndNotify(),
        )
        assertEquals("v1:backup:2026-06-14", harness.dispatched.single().key)
    }

    @Test
    fun deniedDispatchDoesNotMarkSent() = runTest {
        // 权限/开关在 notifier 侧拒绝时不得写假「已提醒」——否则当天修好权限后也收不到。
        val harness = Harness(dispatchOutcome = BackupStaleDispatchOutcome.SKIPPED_PERMISSION_DENIED)
        val outcome = harness.engine.checkAndNotify()
        assertEquals(BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_DISPATCH), outcome)
        assertEquals(1, harness.dispatched.size)
        assertTrue(harness.sent.isEmpty())
    }

    @Test
    fun neverBackedUpStaleCarriesNullAgeHours() = runTest {
        // 无任何备份(后端 None/None/True)→ decision.ageHours=null,notifier 换「还没有任何备份」变体。
        val harness = Harness(
            healthResult = {
                Result.success(ServerBackupHealth(latestBackupAt = null, ageHours = null, stale = true))
            },
        )
        harness.engine.checkAndNotify()
        assertEquals(null, harness.dispatched.single().ageHours)
    }
}
