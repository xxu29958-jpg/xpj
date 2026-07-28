package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.CurrencyCode

/**
 * 账本币种同源裁决（PR#255 R6 P1-1 / R7-1 / R8-1，ADR-0061 C02/C03；R14-6 起为共享实现，
 * 自 DebtListViewModel 提升，供 Goal/Income 三 VM 镜像同一信任口径）：
 * record 级权威值（存量欠款行 installation binding 盖章）与列表信封的安装级 capability
 * 必须同源 ——
 * - 非空账本：record 权威；capability **缺失**（null/blank = 旧服务端无信封字段）不降级。
 * - 空账本：capability 独立解析（服务端 env binding 随信封下发），空账本首笔创建由此放行。
 * - 两源在场却不一致：binding 漂移（C02 声明 installation currency 不可热切换，漂移即异常）
 *   → 冲突 fail closed 归 null，创建保持阻断、草稿不重绑，不猜任一侧。
 * - 全行集合校验（R7-1）：列表 >1 个已知 record 码 = 漂移后新旧 record 并存 → fail closed；
 *   任一 record 未知键（支持集外）→ fail closed。
 * - capability **在场但未知**（R8-1：非 blank 却不在客户端支持集）≠ 缺失 —— 新服务端已宣告
 *   当前 binding 是客户端无法解释的币种，新写入会被服务端按该币种盖章；此时即便 record 已知，
 *   按其口径解析输入也会放大/缩小（VND 零小数 + CNY 解析 "1200" → 120000 minor）→ 一律
 *   fail closed 归 null。判定必须用原始串（先过 knownCurrencyOrNull 会把两态并成 null）。
 */
internal fun resolveLedgerCurrency(recordCodes: List<String>, capabilityCode: String?): CurrencyCode? {
    val capabilityBlank = capabilityCode.isNullOrBlank()
    val capability = knownCurrencyOrNull(capabilityCode)
    if (!capabilityBlank && capability == null) return null // R8-1：在场未知 → fail closed
    val records = recordCodes.map { knownCurrencyOrNull(it) }
    if (records.any { it == null }) return null
    val distinct = records.filterNotNull().distinct()
    // >1 个已知码 = binding 漂移（新旧 record 并存）→ fail closed（不得落 capability 放行）；
    // 空列表无 record 权威，走 capability。
    if (distinct.size > 1) return null
    val record = distinct.singleOrNull()
    if (record != null && capability != null && record != capability) return null
    return record ?: capability
}

/**
 * 列表信封整页的同源裁决便捷重载（R14-6 三 VM 镜像点统一入口）：record 码集合取自
 * `page.debts`，capability 取自信封；拉取失败（page=null）两源皆缺 → fail closed 归 null。
 */
internal fun resolveLedgerCurrency(page: DebtListPage?): CurrencyCode? =
    resolveLedgerCurrency(
        recordCodes = page?.debts?.map { it.homeCurrencyCode } ?: emptyList(),
        capabilityCode = page?.ledgerHomeCurrencyCode,
    )

/** 严格解析：仅客户端支持集内的 storageKey 得币种，其余（null/blank/未知）归 null（R7-2 起委托共享变体）。 */
private fun knownCurrencyOrNull(code: String?): CurrencyCode? = CurrencyCode.fromStorageKeyOrNull(code)
