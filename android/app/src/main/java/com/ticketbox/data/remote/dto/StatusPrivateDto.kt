package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * `GET /api/status/private` 的窄投影(后端 schema=HealthResponse):只建模备份链健康
 * 消费面(轴6 备份超龄通知)。HealthResponse 全字段可空带默认(required 为空),
 * 故窄 DTO 合法——backend_version 等字段 Android 不消费,Moshi 静默丢弃。
 * 已入 [OpenApiContractGateTest] pairs(正向:@Json 名 ⊆ schema 属性)。
 */
data class StatusPrivateDto(
    val status: String,
    @param:Json(name = "latest_backup_at")
    val latestBackupAt: String? = null,
    @param:Json(name = "backup_age_hours")
    val backupAgeHours: Int? = null,
    @param:Json(name = "backup_stale")
    val backupStale: Boolean? = null,
)
