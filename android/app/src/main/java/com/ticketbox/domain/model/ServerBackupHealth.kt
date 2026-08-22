package com.ticketbox.domain.model

/**
 * 服务器备份发布记录年龄(保留 legacy 类型名,server 级、与账本无关)。
 *
 * @property latestBackupAt 最近一次备份时间(ISO 8601 UTC);null=服务器上没有任何备份。
 * @property ageHours 备份年龄(小时,服务端时钟算好);null=无备份。
 * @property stale 发布记录是否超龄。**阈值(48h)在服务端单源**，客户端只消费
 *   布尔、不自带阈值。该对象不表示当前 payload 完整性已复检。
 */
data class ServerBackupHealth(
    val latestBackupAt: String?,
    val ageHours: Int?,
    val stale: Boolean,
)
