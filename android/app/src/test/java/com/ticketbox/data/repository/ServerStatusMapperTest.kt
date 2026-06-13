package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.StatusPrivateDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** [StatusPrivateDto.toBackupHealth]:字段映射 + 老后端缺 `backup_stale` 时保守 false。 */
class ServerStatusMapperTest {

    @Test
    fun mapsBackupFieldsThrough() {
        val health = StatusPrivateDto(
            status = "ok",
            latestBackupAt = "2026-06-10T00:00:00+00:00",
            backupAgeHours = 72,
            backupStale = true,
        ).toBackupHealth()
        assertEquals("2026-06-10T00:00:00+00:00", health.latestBackupAt)
        assertEquals(72, health.ageHours)
        assertTrue(health.stale)
    }

    @Test
    fun missingStaleFieldDefaultsToFalseNotAlert() {
        // 老后端(无备份字段)→ Moshi 留默认 null → 保守不提醒,绝不误报。
        val health = StatusPrivateDto(status = "ok").toBackupHealth()
        assertEquals(null, health.latestBackupAt)
        assertEquals(null, health.ageHours)
        assertFalse(health.stale)
    }
}
