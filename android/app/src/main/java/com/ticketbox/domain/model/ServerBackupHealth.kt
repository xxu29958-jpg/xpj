package com.ticketbox.domain.model

/**
 * 服务器备份链健康(轴6 备份超龄通知的领域模型,server 级、与账本无关)。
 *
 * @property latestBackupAt 最近一次备份时间(ISO 8601 UTC);null=服务器上没有任何备份。
 * @property ageHours 备份年龄(小时,服务端时钟算好);null=无备份。
 * @property stale 是否超龄。**阈值(48h)在服务端单源**(`backup_service.backup_health`),
 *   客户端只消费布尔、不自带阈值;老后端没有该字段时映射为 false(保守不提醒)。
 */
data class ServerBackupHealth(
    val latestBackupAt: String?,
    val ageHours: Int?,
    val stale: Boolean,
)
