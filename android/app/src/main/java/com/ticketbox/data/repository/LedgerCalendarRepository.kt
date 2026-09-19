package com.ticketbox.data.repository

import android.content.SharedPreferences
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.data.remote.dto.toWriteCompatibility
import kotlinx.coroutines.CancellationException

/** Rebuildable rule cache. Full logical binding prevents another principal's rule becoming draft input. */
class LedgerCalendarRepository internal constructor(
    private val guard: LedgerRequestGuard,
    private val preferences: SharedPreferences,
) : LedgerCalendarReader {
    private val moshi = Moshi.Builder().build()
    private val bindingAdapter = moshi.adapter(LogicalSessionBinding::class.java)
    private val ruleAdapter = moshi.adapter(LedgerCalendarDto::class.java)

    override fun currentBinding(): LogicalSessionBinding? = guard.captureLogicalBinding()

    override fun cached(binding: LogicalSessionBinding, revision: Long?): LedgerCalendarDto? {
        val raw = preferences.getString(key(binding, revision), null) ?: return null
        return runCatching { ruleAdapter.fromJson(raw) }.getOrNull()
    }

    override suspend fun refresh(binding: LogicalSessionBinding, revision: Long?): Result<LedgerCalendarDto?> = try {
        val bound = guard.bindExact(binding)
        val rule = bound.call { api ->
            if (!api.runtimeCompatibility().toWriteCompatibility().supportsAccountingTimeInput) null
            else api.ledgerCalendar(binding.ledgerId, revision)
        }
        rule?.let {
            require(it.ledgerId == binding.ledgerId && it.revision > 0 && (revision == null || revision == it.revision))
            java.time.ZoneId.of(it.timezoneName)
            bound.requireStillActive()
            val editor = preferences.edit().putString(key(binding, it.revision), ruleAdapter.toJson(it))
            if (revision == null) editor.putString(key(binding, null), ruleAdapter.toJson(it))
            check(editor.commit()) { "账本日期规则未能保存，请重试。" }
        }
        Result.success(rule)
    } catch (error: CancellationException) {
        throw error
    } catch (error: Exception) {
        Result.failure(error)
    }

    private fun key(binding: LogicalSessionBinding, revision: Long?): String =
        bindingAdapter.toJson(binding) + ":" + (revision?.toString() ?: "current")
}
